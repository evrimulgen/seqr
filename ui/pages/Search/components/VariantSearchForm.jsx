import React from 'react'
import PropTypes from 'prop-types'
import styled from 'styled-components'
import { Field } from 'redux-form'
import { Form, Accordion, Header, Segment } from 'semantic-ui-react'

import { fieldLabel } from 'shared/components/form/ReduxFormWrapper'
import { RadioGroup, LabeledSlider, StepSlider } from 'shared/components/form/Inputs'
import { snakecaseToTitlecase } from 'shared/utils/stringUtils'


const CLINVAR_ANNOTATION_GROUPS = [
  {
    name: 'In Clinvar',
    slug: 'clinvar',
    children: [
      'pathogenic',
      'likely_pathogenic',
      'vus_or_conflicting',
      'likely_benign',
      'benign',
    ],
  },
]

const HGMD_ANNOTATION_GROUPS = [
  {
    name: 'In HGMD',
    slug: 'hgmd',
    children: [ // see https://portal.biobase-international.com/hgmd/pro/global.php#cats
      'disease_causing',
      'likely_disease_causing',
      'hgmd_other',
    ],
  },
]

const VEP_ANNOTATION_GROUPS = [
  {
    name: 'Nonsense',
    slug: 'nonsense',
    children: [
      'stop_gained',
    ],
  },
  {
    name: 'Essential splice site',
    slug: 'essential_splice_site',
    children: [
      'splice_donor_variant',
      'splice_acceptor_variant',
    ],
  },
  {
    name: 'Extended splice site',
    slug: 'extended_splice_site',
    children: [
      'splice_region_variant',
    ],
  },
  {
    name: 'Missense',
    slug: 'missense',
    children: [
      'stop_lost',
      'initiator_codon_variant',
      'start_lost',
      'missense_variant',
      'protein_altering_variant',
    ],
  },
  {
    name: 'Frameshift',
    slug: 'frameshift',
    children: [
      'frameshift_variant',
    ],
  },
  {
    name: 'In Frame',
    slug: 'inframe',
    children: [
      'inframe_insertion',
      'inframe_deletion',
    ],
  },
  {
    name: 'Synonymous',
    slug: 'synonymous',
    children: [
      'synonymous_variant',
      'stop_retained_variant',
    ],
  },
  {
    name: 'Other',
    slug: 'other',
    children: [
      'transcript_ablation',
      'transcript_amplification',
      'incomplete_terminal_codon_variant',
      'coding_sequence_variant',
      'mature_miRNA_variant',
      '5_prime_UTR_variant',
      '3_prime_UTR_variant',
      'intron_variant',
      'NMD_transcript_variant',
      'non_coding_exon_variant', // 2 kinds of 'non_coding_exon_variant' label due to name change in Ensembl v77
      'non_coding_transcript_exon_variant', // 2 kinds of 'non_coding_exon_variant' due to name change in Ensembl v77
      'nc_transcript_variant', // 2 kinds of 'nc_transcript_variant' label due to name change in Ensembl v77
      'non_coding_transcript_variant', // 2 kinds of 'nc_transcript_variant' due to name change in Ensembl v77
      'upstream_gene_variant',
      'downstream_gene_variant',
      'TFBS_ablation',
      'TFBS_amplification',
      'TF_binding_site_variant',
      'regulatory_region_variant',
      'regulatory_region_ablation',
      'regulatory_region_amplification',
      'feature_elongation',
      'feature_truncation',
      'intergenic_variant',
    ],
  },
]

const OPTIONS = [...CLINVAR_ANNOTATION_GROUPS, ...HGMD_ANNOTATION_GROUPS, ...VEP_ANNOTATION_GROUPS].reduce(
  (acc, { name, children }) =>
    [...acc, ...children.map(child => ({ category: name, value: child, text: snakecaseToTitlecase(child) }))],
  [],
)

const QUALITY_FILTER_FIELDS = [
  {
    field: 'vcf_filter',
    label: 'Filter Value',
    labelHelp: 'Either show only variants that PASSed variant quality filters applied when the dataset was processed (typically VQSR or Hard Filters), or show all variants',
    control: RadioGroup,
    options: [{ value: '', text: 'Show All Variants' }, { value: 'pass', text: 'Pass Variants Only' }],
    margin: '1em 0em 0em',
  },
  {
    field: 'min_gq',
    label: 'Genotype Quality',
    labelHelp: 'Genotype Quality (GQ) is a statistical measure of confidence in the genotype call (eg. hom. or het) based on the read data',
    control: LabeledSlider,
    min: 0,
    max: 100,
  },
  {
    field: 'min_ab',
    label: 'Allele Balance',
    labelHelp: 'The allele balance represents the percentage of reads that support the alt allele out of the total number of sequencing reads overlapping a variant. Use this filter to set a minimum percentage for the allele balance in heterozygous individuals.',
    control: LabeledSlider,
    min: 0,
    max: 50,
  },
]

const QUALITY_FILTER_OPTIONS = [
  {
    text: 'High Quality',
    value: {
      vcf_filter: 'pass',
      min_gq: 20,
      min_ab: 25,
    },
  },
  {
    text: 'All Passing Variants',
    value: {
      vcf_filter: 'pass',
      min_gq: 0,
      min_ab: 0,
    },
  },
  {
    text: 'All Variants',
    value: {
      vcf_filter: '',
      min_gq: 0,
      min_ab: 0,
    },
  },
].map(({ value, ...option }) => ({ ...option, value: JSON.stringify(value) }))

const FREQUENCIES = [
  {
    field: '1kg_wgs_phase3',
    label: '1000 Genomes v3',
    homHemi: false,
    labelHelp: 'Filter by allele count (AC) in the 1000 Genomes Phase 3 release (5/2/2013), or by allele frequency (popmax AF) in any one of these five subpopulations defined for 1000 Genomes Phase 3: AFR, AMR, EAS, EUR, SAS',
  },
  {
    field: 'exac_v3',
    label: 'ExAC v0.3',
    homHemi: true,
    labelHelp: 'Filter by allele count (AC) or homozygous/hemizygous count (H/H) in ExAC, or by allele frequency (popmax AF) in any one of these six subpopulations defined for ExAC: AFR, AMR, EAS, FIN, NFE, SAS',
  },
  {
    field: 'gnomad-genomes2',
    label: 'gnomAD 15k genomes',
    homHemi: true,
    labelHelp: 'Filter by allele count (AC) or homozygous/hemizygous count (H/H) among gnomAD genomes, or by allele frequency (popmax AF) in any one of these six subpopulations defined for gnomAD genomes: AFR, AMR, EAS, FIN, NFE, ASJ',
  },
  {
    field: 'gnomad-exomes2',
    label: 'gnomAD 123k exomes',
    homHemi: true,
    labelHelp: 'Filter by allele count (AC) or homozygous/hemizygous count (H/H) among gnomAD exomes, or by allele frequency (popmax AF) in any one of these seven subpopulations defined for gnomAD genomes: AFR, AMR, EAS, FIN, NFE, ASJ, SAS',
  },
  {
    field: 'topmed',
    label: 'TOPMed',
    homHemi: false,
    labelHelp: 'Filter by allele count (AC) or allele frequency (AF) in TOPMed',
  },
  {
    field: 'AF',
    label: 'This Callset',
    homHemi: false,
    labelHelp: 'Filter by allele count (AC) or by allele frequency (AF) among the samples in this family plus the rest of the samples that were joint-called as part of variant calling for this project.',
  },
]

const ToggleHeader = styled(Header).attrs({ size: 'huge', block: true })`
  .dropdown.icon {
    vertical-align: middle !important;
  }

  .content {
    display: inline-block !important;
    width: calc(100% - 2em);
    
    span {
      vertical-align: middle;
      vertical-align: -webkit-baseline-middle;
    }
    
    .field {
      float: right;
      font-size: 0.75em;
      
      .dropdown.icon {
        margin: -0.75em !important;
        transform: rotate(90deg) !important;
      }
    }
  }
`

const ToggleHeaderContent = ({ name, headerInput, title }) =>
  <Header.Content>
    <span>{title}</span>
    {headerInput && <Field name={name} component={headerInput} />}
  </Header.Content>

ToggleHeaderContent.propTypes = {
  title: PropTypes.string.isRequired,
  name: PropTypes.string,
  headerInput: PropTypes.func,
}

const FormSelect = props =>
  <Form.Select value={props.input.value} {...props} onChange={(e, fieldProps) => fieldProps.input.onChange(fieldProps.value)} />

FormSelect.propTypes = {
  input: PropTypes.object,
}


const QualityFilter = ({ input }) =>
  <Form.Group widths="equal">
    {QUALITY_FILTER_FIELDS.map(({ field, label, labelHelp, ...fieldProps }) =>
      <Form.Field
        key={field}
        value={input.value[field]}
        onChange={value => input.onChange({ ...input.value, [field]: value })}
        label={fieldLabel(label, labelHelp)}
        {...fieldProps}
      />,
    )}
  </Form.Group>

QualityFilter.propTypes = {
  input: PropTypes.object,
}

const QualityFilterHeader = ({ input }) =>
  <Form.Select
    value={input.value}
    options={QUALITY_FILTER_OPTIONS}
    onChange={(e, { value }) => input.onChange(value)}
  />

QualityFilterHeader.propTypes = {
  input: PropTypes.object,
}

const AF_STEPS = [
  0,
  0.0001,
  0.0005,
  0.001,
  0.005,
  0.01,
  0.02,
  0.03,
  0.04,
  0.05,
  0.1,
  1,
]

const AF_STEP_LABELS = {
  0.0001: '1e-4',
  0.0005: '5e-4',
  0.001: '1e-3',
  0.005: '5e-3',
}

const FrequencyFilter = ({ input }) =>
  <Form.Group widths="equal">
    {FREQUENCIES.map(({ field, label, labelHelp }) =>
      <Form.Field
        key={field}
        value={input.value[field]}
        onChange={value => input.onChange({ ...input.value, [field]: value })}
        label={fieldLabel(label, labelHelp)}
        control={StepSlider}
        steps={AF_STEPS}
        stepLabels={AF_STEP_LABELS}
      />,
    )}
  </Form.Group>

FrequencyFilter.propTypes = {
  input: PropTypes.object,
}

const PANEL_DETAILS = [
  {
    name: 'annotations',
    title: 'Variant Annotations',
    component: FormSelect,
    label: 'Annotation',
    options: OPTIONS,
    multiple: true,
    format: val => val.split(','),
    parse: val => val.join(','),
  },
  {
    name: 'freqs',
    title: 'Frequency',
    headerInput: null,
    component: FrequencyFilter,
  },
  {
    name: 'qualityFilter',
    title: 'Call Quality',
    headerInput: QualityFilterHeader,
    component: QualityFilter,
  },
]


const PANELS = PANEL_DETAILS.map(({ name, title, headerInput, ...fieldProps }, i) => ({
  key: name,
  title: {
    key: `${name}-title`,
    as: ToggleHeader,
    attached: i === 0 ? 'top' : true,
    content: <ToggleHeaderContent title={title} name={name} headerInput={headerInput} />,
  },
  content: {
    key: name,
    as: Segment,
    attached: i === PANEL_DETAILS.length - 1 ? 'bottom' : true,
    padded: 'very',
    content: <Field name={name} format={val => JSON.parse(val)} parse={val => JSON.stringify(val)} {...fieldProps} />,
  },
}))

const VariantSearchForm = () => <Accordion fluid defaultActiveIndex={1} panels={PANELS} />

export default VariantSearchForm