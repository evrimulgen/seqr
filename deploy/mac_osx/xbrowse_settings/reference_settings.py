import os

from deploy.utils.constants import REFERENCE_DATA_FILES

ensembl_rest_host = "beta.rest.ensembl.org"
ensembl_rest_port = 80
ensembl_db_host = "useastdb.ensembl.org"
ensembl_db_port = 3306
ensembl_db_user = "anonymous"
ensembl_db_password = ""

db_host = 'localhost'
db_port = 27017
db_name = 'xbrowse_reference'

xbrowse_install_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
xbrowse_reference_data_dir = os.path.join(xbrowse_install_dir, 'data/reference_data')

gencode_gtf_file = os.path.join(xbrowse_reference_data_dir, REFERENCE_DATA_FILES['gencode'])
constraint_scores_file = os.path.join(xbrowse_reference_data_dir, REFERENCE_DATA_FILES['constraint_scores'])

gene_list_tags = [
    {
        'slug': 'high_variability',
        'file': os.path.join(xbrowse_reference_data_dir, REFERENCE_DATA_FILES['high_variability_genes'])
    }
]

gene_test_statistic_tags = [
    {
        'slug': 'lof_constraint',
        'data_field': 'pLI'
    },
    {
        'slug': 'missense_constraint',
        'data_field': 'mis_z'
    }
]

gtex_expression_file = os.path.join(xbrowse_reference_data_dir, REFERENCE_DATA_FILES['gtex_expression'])
gtex_samples_file = os.path.join(xbrowse_reference_data_dir, REFERENCE_DATA_FILES['gtex_samples'])

omim_genemap_file = os.path.join(xbrowse_reference_data_dir, REFERENCE_DATA_FILES['omim_genmap'])
clinvar_tsv_file = os.path.join(xbrowse_reference_data_dir, REFERENCE_DATA_FILES['clinvar'])
dbnsfp_gene_file = os.path.join(xbrowse_reference_data_dir, REFERENCE_DATA_FILES['dbnsfp'])

has_phenotype_data = False
