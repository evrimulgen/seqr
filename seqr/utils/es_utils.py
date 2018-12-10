from collections import defaultdict
from copy import deepcopy
from django.db.models import Max
import elasticsearch
from elasticsearch_dsl import Search, Q
import json
import logging
from pyliftover.liftover import LiftOver

import settings
from reference_data.models import GENOME_VERSION_GRCh38, Omim, GeneConstraint
from seqr.models import Sample, Individual
from seqr.utils.xpos_utils import get_xpos
from seqr.utils.gene_utils import parse_locus_list_items
from seqr.views.utils.json_utils import _to_camel_case

logger = logging.getLogger(__name__)


VARIANT_DOC_TYPE = 'variant'


def get_es_client():
    return elasticsearch.Elasticsearch(host=settings.ELASTICSEARCH_SERVICE_HOSTNAME, timeout=30, retry_on_timeout=True)


def get_es_variants(search_model, individuals, page=1, num_results=100):

    start_index = (page - 1) * num_results
    end_index = page * num_results
    if search_model.total_results is not None:
        end_index = min(end_index, search_model.total_results)

    previous_search_results = json.loads(search_model.results or '{}')
    loaded_results = previous_search_results.get('all_results') or []
    if len(loaded_results) >= end_index:
        return loaded_results[start_index:end_index], search_model.total_results
    elif len(loaded_results):
        start_index = max(start_index, len(loaded_results))

    search = json.loads(search_model.search)
    sort = search_model.sort

    genes, intervals, invalid_items = parse_locus_list_items(search.get('locus', {}), all_new=True)
    if invalid_items:
        raise Exception('Invalid genes/intervals: {}'.format(', '.join(invalid_items)))

    samples = Sample.objects.filter(
        individual__in=individuals,
        dataset_type=Sample.DATASET_TYPE_VARIANT_CALLS,
        sample_status=Sample.SAMPLE_STATUS_LOADED,
        elasticsearch_index__isnull=False,
    )
    sample_individual_max_loaded_date = {
        agg['individual__guid']: agg['max_loaded_date'] for agg in
        samples.values('individual__guid').annotate(max_loaded_date=Max('loaded_date'))
    }
    samples = [s for s in samples if s.loaded_date == sample_individual_max_loaded_date[s.individual.guid]]

    elasticsearch_index = search_model.es_index
    if not elasticsearch_index:
        es_indices = {s.elasticsearch_index for s in samples}
        if len(es_indices) > 1:
            # TODO get rid of this once add multi-project support and handle duplicate variants in different indices
            raise Exception('Samples are not all contained in the same index: {}'.format(', '.join(es_indices)))
        elasticsearch_index = ','.join(es_indices)

    #  TODO does not work across projects/ families?
    samples_by_id = {sample.sample_id: sample for sample in samples}

    #  TODO move liftover to hail pipeline once upgraded to 0.2
    liftover_grch38_to_grch37 = None
    try:
        liftover_grch38_to_grch37 = LiftOver('hg38', 'hg19')
    except Exception as e:
        logger.warn('WARNING: Unable to set up liftover. {}'.format(e))

    es_search = Search(using=get_es_client(), index=elasticsearch_index)

    if genes or intervals:
        es_search = es_search.filter(_location_filter(genes, intervals, search['locus']))

    allowed_consequences = None
    if search.get('annotations'):
        consequences_filter, allowed_consequences = _annotations_filter(search['annotations'])
        es_search = es_search.filter(consequences_filter)

    if search.get('freqs'):
        es_search = es_search.filter(_frequency_filter(search['freqs']))

    genotypes_q, inheritance_mode, compound_het_q = _genotype_filter(
        search.get('inheritance'), search.get('qualityFilter'), individuals, samples_by_id,
    )
    compound_het_search = None
    if compound_het_q:
        compound_het_search = es_search.filter(compound_het_q)
    es_search = es_search.filter(genotypes_q)

    if inheritance_mode == RECESSIVE:
        # recessive results are merged with compound het results so need to load all results through the end of the requested page,
        # not just a single page's worth of results (i.e. when skipping pages need to load middle pages as well)
        start_index = len(previous_search_results.get('variant_results') or [])

    es_search = es_search[start_index:end_index]

    field_names = _get_query_field_names()
    sort = _get_sort(sort, samples_by_id)

    variant_results = []
    total_results = 0
    if inheritance_mode != COMPOUND_HET:
        es_search = es_search.source(field_names)
        es_search = es_search.sort(*sort)

        logger.info('Searching in elasticsearch index: {}'.format(elasticsearch_index))
        logger.info(json.dumps(es_search.to_dict(), indent=2))

        response = es_search.execute()
        total_results = response.hits.total
        logger.info('Total hits: {} ({} seconds)'.format(total_results, response.took / 100.0))

        variant_results = [_parse_es_hit(hit, samples_by_id, liftover_grch38_to_grch37, field_names) for hit in response]

    compound_het_results = previous_search_results.get('compound_het_results')
    total_compound_het_results = None
    if inheritance_mode in [COMPOUND_HET, RECESSIVE] and compound_het_results is None:
        # For compound het search get results from aggregation instead of top level hits
        compound_het_search = compound_het_search[:0] if compound_het_search else es_search[:0]
        compound_het_search.aggs.bucket(
            'genes', 'terms', field='geneIds', min_doc_count=2, size=10000
        ).metric(
            'vars_by_gene', 'top_hits', size=100, sort=sort, _source=field_names
        )

        logger.info('Searching in elasticsearch index: {}'.format(elasticsearch_index))
        logger.info(json.dumps(compound_het_search.to_dict(), indent=2))

        response = compound_het_search.execute()

        compound_het_results, total_compound_het_results = _parse_compound_het_hits(
            response, allowed_consequences, samples_by_id, liftover_grch38_to_grch37, field_names
        )
        logger.info('Total compound het hits: {}'.format(total_compound_het_results))

    if compound_het_results:
        previous_search_results['compound_het_results'] = compound_het_results
        variant_results += previous_search_results.get('variant_results', [])
        previous_search_results['variant_results'] =variant_results

        if total_compound_het_results is not None:
            total_results += total_compound_het_results
        else:
            total_results = search_model.total_results

        grouped_variants = compound_het_results

        if variant_results:
            grouped_variants += [[var] for var in variant_results]

        # Sort merged result sets
        grouped_variants = sorted(grouped_variants, key=lambda variants: tuple(variants[0]['_sort']))

        # Only return the requested page of variants
        start_index = max(len(loaded_results), (page - 1) * num_results)
        skipped = 0
        variant_results = []
        for variants in grouped_variants:
            if skipped < start_index:
                if start_index > len(loaded_results):
                    loaded_results += variants
                skipped += len(variants)
            else:
                variant_results += variants
                if len(variant_results) >= num_results:
                    break

    # Only save contiguous pages of results
    if len(loaded_results) == start_index:
        previous_search_results['all_results'] = loaded_results + variant_results

    search_model.results = json.dumps(previous_search_results)
    search_model.total_results = total_results
    search_model.es_index = elasticsearch_index
    search_model.save()

    return variant_results, total_results


AFFECTED = Individual.AFFECTED_STATUS_AFFECTED
UNAFFECTED = Individual.AFFECTED_STATUS_UNAFFECTED
ALT_ALT = 'alt_alt'
REF_REF = 'ref_ref'
REF_ALT = 'ref_alt'
HAS_ALT = 'has_alt'
HAS_REF = 'has_ref'
# TODO no call?
GENOTYPE_QUERY_MAP = {
    REF_REF: 0,
    REF_ALT: 1,
    ALT_ALT: 2,
    HAS_ALT: {'gte': 1},
    HAS_REF: {'gte': 0, 'lte': 1},
}
RANGE_FIELDS = {k for k, v in GENOTYPE_QUERY_MAP.items() if type(v) != int}

RECESSIVE = 'recessive'
X_LINKED_RECESSIVE = 'x_linked_recessive'
HOMOZYGOUS_RECESSIVE = 'homozygous_recessive'
COMPOUND_HET = 'compound_het'
RECESSIVE_FILTER = {
    AFFECTED: ALT_ALT,
    UNAFFECTED: HAS_REF,
}
INHERITANCE_FILTERS = {
   RECESSIVE: RECESSIVE_FILTER,
   X_LINKED_RECESSIVE: RECESSIVE_FILTER,
   HOMOZYGOUS_RECESSIVE: RECESSIVE_FILTER,
   COMPOUND_HET: {
       AFFECTED: REF_ALT,
       UNAFFECTED: HAS_REF,
   },
   'de_novo': {
       AFFECTED: HAS_ALT,
       UNAFFECTED: REF_REF,
   },
}


def _genotype_filter(inheritance, quality_filter, individuals, samples_by_id):
    genotypes_q = Q()
    compound_het_q = None
    inheritance_mode = None

    quality_q = Q()
    if quality_filter:
        if quality_filter.get('vcf_filter') is not None:
            genotypes_q = ~Q('exists', field='filters')

        min_ab = quality_filter['min_ab'] / 100.0 if quality_filter.get('min_ab') else None
        min_gq = quality_filter.get('min_gq')
        if min_ab:
            #  AB only relevant for hets
            quality_q &= Q(~Q('term', num_alt=1) | Q('range', ab={'gte': min_ab}))
        if min_gq:
            quality_q &= Q('range', gq={'gte': min_gq})

    if inheritance:
        samples_q, addl_filter, inheritance_mode = _genotype_inheritance_filter(inheritance, quality_q, individuals, samples_by_id)
        if addl_filter:
            genotypes_q &= addl_filter
    else:
        samples_q = Q('terms', sample_id=samples_by_id.keys()) & quality_q
        # If no inheritance specified only return variants where at least one of the requested samples has an alt allele
        # TODO this should be on a per-family basis (i.e. only return families with at least one alt allele)
        genotypes_q &= Q('has_child', type='genotype', query=Q(Q('range', num_alt={'gte': 1}) & samples_q))

    # Return variants where all requested samples meet the filtering criteria
    genotypes_child_q = _genotypes_child_q(samples_q, samples_by_id)

    # For recessive search, should be hom recessive, x-linked recessive, or compound het
    if inheritance_mode == RECESSIVE:
        compound_het_q, _, _ = _genotype_inheritance_filter(
            inheritance, quality_q, individuals, samples_by_id, inheritance_mode=COMPOUND_HET,
        )
        compound_het_q = _genotypes_child_q(compound_het_q, samples_by_id)
        x_linked_q, addl_filter, _ = _genotype_inheritance_filter(
            inheritance, quality_q, individuals, samples_by_id, inheritance_mode=X_LINKED_RECESSIVE
        )
        genotypes_child_q |= Q(addl_filter & _genotypes_child_q(x_linked_q, samples_by_id))

    genotypes_q &= genotypes_child_q

    return genotypes_q, inheritance_mode, compound_het_q


def _genotypes_child_q(samples_q, samples_by_id):
    return Q('has_child', type='genotype', query=samples_q, min_children=len(samples_by_id), inner_hits={})


def _genotype_inheritance_filter(inheritance, quality_q, individuals, samples_by_id, inheritance_mode=None):
    samples_q = None
    global_filter = None

    inheritance_mode = inheritance_mode or inheritance.get('mode')
    inheritance_filter = inheritance.get('filter') or {}
    individual_genotype_filter = inheritance_filter.get('genotype') or {}
    individual_affected_status = inheritance_filter.get('affected') or {}
    for individual in individuals:
        if not individual_affected_status.get(individual.guid):
            individual_affected_status[individual.guid] = individual.affected

    if individual_genotype_filter:
        inheritance_mode = None
        logger.info('CUSTOM GENOTYPE FILTER: {}'.format(', '.join(individual_genotype_filter.keys())))

    if inheritance_mode:
        inheritance_filter.update(INHERITANCE_FILTERS[inheritance_mode])

    parent_x_linked_genotypes = {}
    if inheritance_mode == X_LINKED_RECESSIVE:
        global_filter = Q('match', contig='X')
        for individual in individuals:
            if individual_affected_status[individual.guid] == AFFECTED:
                if individual.mother and individual_affected_status[individual.mother.guid] == UNAFFECTED:
                    parent_x_linked_genotypes[individual.mother.guid] = REF_ALT
                if individual.father and individual_affected_status[individual.father.guid] == UNAFFECTED:
                    parent_x_linked_genotypes[individual.mother.guid] = REF_REF

    for sample_id, sample in samples_by_id.items():
        sample_q = Q(Q('term', sample_id=sample_id) & quality_q)
        individual_guid = sample.individual.guid
        affected = individual_affected_status[individual_guid]

        genotype = individual_genotype_filter.get(individual_guid) \
                   or parent_x_linked_genotypes.get(individual_guid) \
                   or inheritance_filter.get(affected)

        if genotype:
            sample_q &= Q('range' if genotype in RANGE_FIELDS else 'term', num_alt=GENOTYPE_QUERY_MAP[genotype])

        if not samples_q:
            samples_q = sample_q
        else:
            samples_q |= sample_q

    return samples_q, global_filter, inheritance_mode


def _location_filter(genes, intervals, location_filter):
    q = None
    if intervals:
        q = _build_or_filter('range', [{
            'xpos': {
                'gte': get_xpos(interval['chrom'], interval['start']),
                'lte': get_xpos(interval['chrom'], interval['end'])
            }
        } for interval in intervals])

    if genes:
        gene_q = Q('terms', geneIds=genes.keys())
        if q:
            q |= gene_q
        else:
            q = gene_q

    if location_filter.get('excludeLocations'):
        return ~q
    else:
        return q


CLINVAR_SIGNFICANCE_MAP = {
    'pathogenic': ['Pathogenic', 'Pathogenic/Likely_pathogenic'],
    'likely_pathogenic': ['Likely_pathogenic', 'Pathogenic/Likely_pathogenic'],
    'benign': ['Benign', 'Benign/Likely_benign'],
    'likely_benign': ['Likely_benign', 'Benign/Likely_benign'],
    'vus_or_conflicting': [
        'Conflicting_interpretations_of_pathogenicity',
        'Uncertain_significance',
        'not_provided',
        'other'
    ],
}

HGMD_CLASS_MAP = {
    'disease_causing': ['DM'],
    'likely_disease_causing': ['DM?'],
    'hgmd_other': ['DP', 'DFP', 'FP', 'FTV'],
}


def _annotations_filter(annotations):
    annotations = deepcopy(annotations)
    clinvar_filters = annotations.pop('clinvar', [])
    hgmd_filters = annotations.pop('hgmd', [])
    vep_consequences = [ann for annotations in annotations.values() for ann in annotations]

    consequences_filter = Q('terms', transcriptConsequenceTerms=vep_consequences)

    if clinvar_filters:
        clinvar_clinical_significance_terms = set()
        for clinvar_filter in clinvar_filters:
            clinvar_clinical_significance_terms.update(CLINVAR_SIGNFICANCE_MAP.get(clinvar_filter, []))
        consequences_filter |= Q('terms', clinvar_clinical_significance=list(clinvar_clinical_significance_terms))

    if hgmd_filters:
        hgmd_class = set()
        for hgmd_filter in hgmd_filters:
            hgmd_class.update(HGMD_CLASS_MAP.get(hgmd_filter, []))
        consequences_filter |= Q('terms', hgmd_class=list(hgmd_class))

    if 'intergenic_variant' in vep_consequences:
        # for many intergenic variants VEP doesn't add any annotations, so if user selected 'intergenic_variant', also match variants where transcriptConsequenceTerms is emtpy
        consequences_filter |= ~Q('exists', field='transcriptConsequenceTerms')

    return consequences_filter, vep_consequences


POPULATIONS = {
    'callset': {
        'AF': 'AF',
        'AC': 'AC',
        'AN': 'AN',
    },
    'topmed': {
        'use_default_field_suffix': True,
    },
    'g1k': {
        'AF': 'g1k_POPMAX_AF',
    },
    'exac': {
        'AF': 'exac_AF_POPMAX',
        'AC': 'exac_AC_Adj',
        'AN': 'exac_AN_Adj',
        'Hom': 'exac_AC_Hom',
        'Hemi': 'exac_AC_Hemi',
    },
    'gnomad_exomes': {},
    'gnomad_genomes': {},
}
POPULATION_FIELD_CONFIGS = {
    'AF': {'fields': ['AF_POPMAX_OR_GLOBAL'], 'format_value': float},
    'AC': {},
    'AN': {},
    'Hom': {},
    'Hemi': {},
}


def _get_pop_freq_key(population, freq_field):
    pop_config = POPULATIONS[population]
    field_config = POPULATION_FIELD_CONFIGS[freq_field]
    freq_suffix = freq_field
    if field_config.get('fields') and not pop_config.get('use_default_field_suffix'):
        freq_suffix = field_config['fields'][-1]
    return pop_config.get(freq_field) or '{}_{}'.format(population, freq_suffix)


def _pop_freq_filter(filter_key, value):
    return Q('range', **{filter_key: {'lte': value}}) | ~Q('exists', field=filter_key)


def _frequency_filter(frequencies):
    q = Q()
    for pop, freqs in frequencies.items():
        if freqs.get('af'):
            q &= _pop_freq_filter(_get_pop_freq_key(pop, 'AF'), freqs['af'])
        elif freqs.get('ac'):
            q &= _pop_freq_filter(_get_pop_freq_key(pop, 'AC'), freqs['ac'])

        if freqs.get('hh'):
            q &= _pop_freq_filter(_get_pop_freq_key(pop, 'Hom'), freqs['hh'])
            q &= _pop_freq_filter(_get_pop_freq_key(pop, 'Hemi'), freqs['hh'])
    return q


def _build_or_filter(op, filters):
    if not filters:
        return None
    q = Q(op, **filters[0])
    for filter_kwargs in filters[1:]:
        q |= Q(op, **filter_kwargs)
    return q


def _get_family_samples(samples_by_id):
    family_samples = defaultdict(list)
    for sample_id, sample in samples_by_id.items():
        family_samples[sample.individual.family.guid].append(sample_id)
    return family_samples


PATHOGENICTY_SORT_KEY = 'pathogenicity'
PATHOGENICTY_HGMD_SORT_KEY = 'pathogenicity_hgmd'
XPOS_SORT_KEY = 'xpos'
CLINVAR_SORT = {
    '_script': {
        'type': 'number',
        'script': {
           'source': """
                if (doc['clinvar_clinical_significance'].empty ) {
                    return 2;
                }
                String clinsig = doc['clinvar_clinical_significance'].value;
                if (clinsig.indexOf('Pathogenic') >= 0 || clinsig.indexOf('Likely_pathogenic') >= 0) {
                    return 0;
                } else if (clinsig.indexOf('Benign') >= 0 || clinsig.indexOf('Likely_benign') >= 0) {
                    return 3;
                }
                return 1;
           """
        }
    }
}
#  TODO family sort with nested genotypes
SORT_FIELDS = {
    'family_guid': [{
        '_script': {
            'type': 'string',
            'script': {
                'params': {
                    'family_samples': _get_family_samples
                },
                'source': """ArrayList families = new ArrayList(params.family_samples.keySet()); families.sort((a, b) -> a.compareTo(b)); for (family in families) { for (sample in params.family_samples[family]) {if(doc.containsKey(sample+"_num_alt") && params._source[sample+\"_num_alt\"] >= 0) {return family;}}}return "zz";"""
            }
        }
    }],
    PATHOGENICTY_SORT_KEY: [CLINVAR_SORT],
    PATHOGENICTY_HGMD_SORT_KEY: [CLINVAR_SORT, {
        '_script': {
            'type': 'number',
            'script': {
               'source': "(!doc['hgmd_class'].empty && doc['hgmd_class'].value == 'DM') ? 0 : 1"
            }
        }
    }],
    'in_omim': [{
        '_script': {
            'type': 'number',
            'script': {
                'params': {
                    'omim_gene_ids': lambda *args: [omim.gene.gene_id for omim in Omim.objects.all().only('gene__gene_id')]
                },
                'source': "params.omim_gene_ids.contains(doc['mainTranscript_gene_id'].value) ? 0 : 1"
            }
        }
    }],
    'protein_consequence': ['mainTranscript_major_consequence_rank'],
    'exac': [{_get_pop_freq_key('exac', 'AF'): {'missing': '_first'}}],
    '1kg': [{_get_pop_freq_key('g1k', 'AF'): {'missing': '_first'}}],
    'constraint': [{
        '_script': {
            'order': 'asc',
            'type': 'number',
            'script': {
                'params': {
                    'constraint_ranks_by_gene': lambda *args: {
                        constraint.gene.gene_id: constraint.mis_z_rank + constraint.pLI_rank
                        for constraint in GeneConstraint.objects.all().only('gene__gene_id', 'mis_z_rank', 'pLI_rank')}
                },
                'source': "params.constraint_ranks_by_gene.getOrDefault(doc['mainTranscript_gene_id'].value, 10000000)"
            }
        }
    }],
    XPOS_SORT_KEY: ['xpos'],
}


def _get_sort(sort_key, *args):
    sorts = SORT_FIELDS.get(sort_key, [])

    # Add parameters to scripts
    if len(sorts) and isinstance(sorts[0], dict) and sorts[0].get('_script', {}).get('script', {}).get('params'):
        for key, val_func in sorts[0]['_script']['script']['params'].items():
            sorts[0]['_script']['script']['params'][key] = val_func(*args)

    if XPOS_SORT_KEY not in sorts:
        sorts.append(XPOS_SORT_KEY)
    return sorts


CLINVAR_FIELDS = ['clinical_significance', 'variation_id', 'allele_id', 'gold_stars']
HGMD_FIELDS = ['accession', 'class']
SORTED_TRANSCRIPTS_FIELD_KEY = 'sortedTranscriptConsequences'
NESTED_FIELDS = {
    field_name: {field: {} for field in fields} for field_name, fields in {
        'clinvar': CLINVAR_FIELDS,
        'hgmd': HGMD_FIELDS,
    }.items()
}

CORE_FIELDS_CONFIG = {
    'variantId': {},
    'alt': {},
    'contig': {'response_key': 'chrom'},
    'start': {'response_key': 'pos', 'format_value': long},
    'filters': {'response_key': 'genotypeFilters', 'format_value': lambda filters: ','.join(filters), 'default_value': []},
    'originalAltAlleles': {'format_value': lambda alleles: [a.split('-')[-1] for a in alleles], 'default_value': []},
    'ref': {},
    'rsid': {},
    'xpos': {'format_value': long},
}
PREDICTION_FIELDS_CONFIG = {
    'cadd_PHRED': {'response_key': 'cadd'},
    'dbnsfp_DANN_score': {},
    'eigen_Eigen_phred': {},
    'dbnsfp_FATHMM_pred': {},
    'dbnsfp_GERP_RS': {'response_key': 'gerp_rs'},
    'mpc_MPC': {},
    'dbnsfp_MetaSVM_pred': {},
    'dbnsfp_MutationTaster_pred': {'response_key': 'mut_taster'},
    'dbnsfp_phastCons100way_vertebrate': {'response_key': 'phastcons_100_vert'},
    'dbnsfp_Polyphen2_HVAR_pred': {'response_key': 'polyphen'},
    'primate_ai_score': {'response_key': 'primate_ai'},
    'dbnsfp_REVEL_score': {},
    'dbnsfp_SIFT_pred': {},
}
GENOTYPE_FIELDS_CONFIG = {
    'ab': {},
    'ad': {},
    'dp': {},
    'gq': {},
    'pl': {},
    'num_alt': {'format_value': int, 'default_value': -1},
}

DEFAULT_POP_FIELD_CONFIG = {
    'format_value': int,
    'default_value': 0,
    'no_key_use_default': False,
}
POPULATION_RESPONSE_FIELD_CONFIGS = {k: dict(DEFAULT_POP_FIELD_CONFIG, **v) for k, v in POPULATION_FIELD_CONFIGS.items()}


def _get_query_field_names():
    field_names = CORE_FIELDS_CONFIG.keys() + PREDICTION_FIELDS_CONFIG.keys() + [SORTED_TRANSCRIPTS_FIELD_KEY]
    for field_name, fields in NESTED_FIELDS.items():
        field_names += ['{}_{}'.format(field_name, field) for field in fields.keys()]
    for population, pop_config in POPULATIONS.items():
        for field, field_config in POPULATION_RESPONSE_FIELD_CONFIGS.items():
            if pop_config.get(field):
                field_names.append(pop_config.get(field))
            field_names.append('{}_{}'.format(population, field))
            field_names += ['{}_{}'.format(population, custom_field) for custom_field in field_config.get('fields', [])]
    return field_names


def _parse_es_hit(raw_hit, samples_by_id, liftover_grch38_to_grch37, field_names):
    genotypes = {}
    matched_samples = set()
    for genotype_hit in raw_hit.meta.inner_hits.genotype:
        sample = samples_by_id[genotype_hit['sample_id']]
        matched_samples.add(sample)
        genotypes[sample.guid] = _get_field_values(genotype_hit, GENOTYPE_FIELDS_CONFIG)

    hit = {k: raw_hit[k] for k in field_names if k in raw_hit}

    # TODO better handling for multi-family/ project searches
    family = matched_samples.pop().individual.family
    project = family.project

    genome_version = project.genome_version
    lifted_over_genome_version = None
    lifted_over_chrom= None
    lifted_over_pos = None
    if liftover_grch38_to_grch37 and genome_version == GENOME_VERSION_GRCh38:
        if liftover_grch38_to_grch37:
            grch37_coord = liftover_grch38_to_grch37.convert_coordinate(
                'chr{}'.format(hit['contig'].lstrip('chr')), int(hit['start'])
            )
            if grch37_coord and grch37_coord[0]:
                lifted_over_chrom = grch37_coord[0][0].lstrip('chr')
                lifted_over_pos = grch37_coord[0][1]

    populations = {
        population: _get_field_values(
            hit, POPULATION_RESPONSE_FIELD_CONFIGS, format_response_key=lambda key: key.lower(), lookup_field_prefix=population,
            get_addl_fields=lambda field, field_config:
                [pop_config.get(field)] + ['{}_{}'.format(population, custom_field) for custom_field in field_config.get('fields', [])],
        )
        for population, pop_config in POPULATIONS.items()
    }

    sorted_transcripts = [
        {_to_camel_case(k): v for k, v in transcript.to_dict().items()}
        for transcript in hit[SORTED_TRANSCRIPTS_FIELD_KEY]
    ]
    transcripts = defaultdict(list)
    for transcript in sorted_transcripts:
        transcripts[transcript['geneId']].append(transcript)

    result = _get_field_values(hit, CORE_FIELDS_CONFIG, format_response_key=str)
    result.update({
        field_name: _get_field_values(hit, fields, lookup_field_prefix=field_name)
        for field_name, fields in NESTED_FIELDS.items()
    })
    result.update({
        'projectGuid': project.guid,
        'familyGuid': family.guid,
        'genotypes': genotypes,
        'genomeVersion': genome_version,
        'liftedOverGenomeVersion': lifted_over_genome_version,
        'liftedOverChrom': lifted_over_chrom,
        'liftedOverPos': lifted_over_pos,
        'mainTranscript': sorted_transcripts[0] if len(sorted_transcripts) else {},
        'populations': populations,
        'predictions': _get_field_values(
            hit, PREDICTION_FIELDS_CONFIG, format_response_key=lambda key: key.split('_')[1].lower()
        ),
        'transcripts': transcripts,
        '_sort': [_parse_es_sort(sort) for sort in raw_hit.meta.sort],
    })
    return result


def _parse_compound_het_hits(response, allowed_consequences, samples_by_id, *args):
    unaffected_indiv_sample_guids = [sample.guid for sample in samples_by_id.values()
                                     if sample.individual.affected == UNAFFECTED]

    variants_by_gene = []
    try:
        response.aggregations.genes.buckets
    except Exception as e:
        import pdb; pdb.set_trace()
    for gene_agg in response.aggregations.genes.buckets:
        gene_variants = [_parse_es_hit(hit, samples_by_id, *args) for hit in gene_agg['vars_by_gene']]

        if allowed_consequences:
            # Variants are returned if any transcripts have the filtered consequence, but to be compound het
            # the filtered consequence needs to be present in at least one transcript in the gene of interest
            gene_variants = [variant for variant in gene_variants if any(
                transcript['majorConsequence'] in allowed_consequences for transcript in
                variant['transcripts'][gene_agg['key']]
            )]

        if len(gene_variants) > 1:
            is_compound_het = True
            for sample_guid in unaffected_indiv_sample_guids:
                # To be compound het all unaffected individuals need to be hom ref for at least one of the variants
                is_compound_het = any(
                    variant['genotypes'].get(sample_guid, {}).get('numAlt') != 1 for variant in gene_variants)
                if not is_compound_het:
                    break

            if is_compound_het:
                variants_by_gene.append(gene_variants)

    return variants_by_gene, sum(len(results) for results in variants_by_gene)


def _parse_es_sort(sort):
    if sort == 'Infinity':
        sort = float('inf')
    elif sort == '-Infinity':
        sort = float('-inf')
    return sort


def _get_field_values(hit, field_configs, format_response_key=_to_camel_case, get_addl_fields=None, lookup_field_prefix=''):
    return {
        field_config.get('response_key', format_response_key(field)): _value_if_has_key(
            hit,
            (get_addl_fields(field, field_config) if get_addl_fields else []) +
            ['{}_{}'.format(lookup_field_prefix, field) if lookup_field_prefix else field],
            **field_config
        )
        for field, field_config in field_configs.items()
    }


def _value_if_has_key(hit, keys, format_value=None, default_value=None, no_key_use_default=True, **kwargs):
    for key in keys:
        if key in hit:
            return format_value(default_value if hit[key] is None else hit[key]) if format_value else hit[key]
    return default_value if no_key_use_default else None
