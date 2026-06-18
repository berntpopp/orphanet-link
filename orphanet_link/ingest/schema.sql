-- orphanet-link SQLite schema (SCHEMA_VERSION = 1).
-- Built atomically by ingest/builder.py; queried read-only by data/repository.py.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = OFF;

-- Core nomenclature (product 1) ---------------------------------------------
CREATE TABLE disorder (
    orpha_code      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    name_upper      TEXT NOT NULL,
    disorder_type   TEXT,          -- e.g. Disease, Malformation syndrome, Clinical subtype
    disorder_group  TEXT,          -- Group of disorders | Disorder | Subtype of a disorder
    disorder_flag   TEXT,
    expert_link     TEXT,
    definition      TEXT,
    is_obsolete     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_disorder_name_upper ON disorder (name_upper);

CREATE TABLE disorder_synonym (
    orpha_code TEXT NOT NULL,
    synonym    TEXT NOT NULL
);
CREATE INDEX idx_disorder_synonym ON disorder_synonym (orpha_code);

CREATE TABLE disorder_lookup (     -- label/synonym -> code resolution
    lookup_label TEXT NOT NULL,
    orpha_code   TEXT NOT NULL,
    label_type   TEXT NOT NULL     -- name | synonym
);
CREATE INDEX idx_disorder_lookup ON disorder_lookup (lookup_label);

CREATE VIRTUAL TABLE disorder_fts USING fts5 (
    orpha_code UNINDEXED,
    name,
    synonyms,
    tokenize = 'porter unicode61'
);

-- Cross-references (product 1) ----------------------------------------------
CREATE TABLE xref (
    orpha_code        TEXT NOT NULL,
    source            TEXT NOT NULL,   -- OMIM | MONDO | ICD-10 | ICD-11 | UMLS | GARD | MeSH | MedDRA
    object_id         TEXT NOT NULL,
    object_id_upper   TEXT NOT NULL,
    mapping_relation  TEXT,            -- E | NTBT | BTNT | ND | W
    icd_relation      TEXT,
    validation_status TEXT,            -- Validated | (other)
    ref_uri           TEXT             -- WHO Foundation URI for ICD-11
);
CREATE INDEX idx_xref_orpha ON xref (orpha_code);
CREATE INDEX idx_xref_obj   ON xref (source, object_id_upper);

-- Classification (product 3, poly-hierarchy) + precomputed closure ----------
CREATE TABLE classification_edge (
    orpha_code   TEXT NOT NULL,
    parent_code  TEXT NOT NULL,
    specialty_id TEXT NOT NULL
);
CREATE INDEX idx_class_edge_child  ON classification_edge (orpha_code);
CREATE INDEX idx_class_edge_parent ON classification_edge (parent_code);

CREATE TABLE classification_closure (
    orpha_code    TEXT NOT NULL,
    ancestor_code TEXT NOT NULL
);
CREATE INDEX idx_class_closure     ON classification_closure (orpha_code);
CREATE INDEX idx_class_closure_anc ON classification_closure (ancestor_code);

CREATE TABLE specialty (
    specialty_id TEXT PRIMARY KEY,
    name         TEXT NOT NULL
);

-- Linearisation (product 7, single parent) ----------------------------------
CREATE TABLE linearisation (
    orpha_code  TEXT NOT NULL,
    parent_code TEXT
);
CREATE INDEX idx_linearisation ON linearisation (orpha_code);

-- Genes (product 6) ----------------------------------------------------------
CREATE TABLE gene (
    gene_symbol  TEXT PRIMARY KEY,
    gene_name    TEXT,
    gene_type    TEXT,
    locus        TEXT,
    hgnc_id      TEXT,
    omim_id      TEXT,
    ensembl_id   TEXT,
    swissprot_id TEXT,
    genatlas_id  TEXT,
    reactome_id  TEXT,
    clinvar_id   TEXT
);

CREATE TABLE disorder_gene (
    orpha_code         TEXT NOT NULL,
    gene_symbol        TEXT NOT NULL,
    association_type   TEXT,   -- e.g. Disease-causing germline mutation(s) in
    association_status TEXT,   -- Assessed | Not yet assessed
    source_pmids       TEXT
);
CREATE INDEX idx_disorder_gene_orpha ON disorder_gene (orpha_code);
CREATE INDEX idx_disorder_gene_sym   ON disorder_gene (gene_symbol);

-- Phenotypes (product 4) -----------------------------------------------------
CREATE TABLE phenotype (
    orpha_code          TEXT NOT NULL,
    hpo_id              TEXT NOT NULL,
    hpo_term            TEXT,
    frequency           TEXT,   -- Obligate | Very frequent | Frequent | Occasional | Very rare | Excluded
    diagnostic_criteria TEXT
);
CREATE INDEX idx_phenotype_orpha ON phenotype (orpha_code);
CREATE INDEX idx_phenotype_hpo   ON phenotype (hpo_id);

-- Epidemiology (product 9 prev) ----------------------------------------------
CREATE TABLE prevalence (
    orpha_code        TEXT NOT NULL,
    prevalence_type   TEXT,
    prevalence_class  TEXT,
    val_moy           REAL,
    geographic        TEXT,
    qualification     TEXT,
    validation_status TEXT,
    source            TEXT
);
CREATE INDEX idx_prevalence_orpha ON prevalence (orpha_code);

-- Natural history (product 9 ages) -------------------------------------------
CREATE TABLE age_of_onset (
    orpha_code TEXT NOT NULL,
    onset      TEXT NOT NULL
);
CREATE INDEX idx_onset_orpha ON age_of_onset (orpha_code);

CREATE TABLE inheritance (
    orpha_code  TEXT NOT NULL,
    inheritance TEXT NOT NULL
);
CREATE INDEX idx_inheritance_orpha ON inheritance (orpha_code);

-- Disability / functional consequences (en_funct_consequences) ---------------
CREATE TABLE disability (
    orpha_code  TEXT NOT NULL,
    annotation  TEXT,
    frequency   TEXT,
    temporality TEXT,
    severity    TEXT
);
CREATE INDEX idx_disability_orpha ON disability (orpha_code);

-- Provenance (single row) ----------------------------------------------------
CREATE TABLE meta (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version   INTEGER,
    orphanet_version TEXT,     -- <JDBOR version=>
    orphanet_date    TEXT,     -- <JDBOR date=>
    source_urls      TEXT,     -- JSON map of product -> URL
    disorder_count   INTEGER,
    xref_count       INTEGER,
    gene_count       INTEGER,
    phenotype_count  INTEGER,
    prevalence_count INTEGER,
    closure_count    INTEGER,
    build_utc        TEXT,
    build_duration_s REAL
);
