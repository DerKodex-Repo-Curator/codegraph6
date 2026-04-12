// Neo4j schema initialization for Oopsly
// Run once after the database starts.
// Safe to re-run – all statements use IF NOT EXISTS.

// ---------------------------------------------------------------------------
// Uniqueness constraints (also create backing B-tree indexes)
// ---------------------------------------------------------------------------

CREATE CONSTRAINT repo_url_unique IF NOT EXISTS
    FOR (r:Repository) REQUIRE r.url IS UNIQUE;

CREATE CONSTRAINT file_path_unique IF NOT EXISTS
    FOR (f:File) REQUIRE f.path IS UNIQUE;

CREATE CONSTRAINT class_qname_unique IF NOT EXISTS
    FOR (c:Class) REQUIRE c.qualified_name IS UNIQUE;

CREATE CONSTRAINT function_qname_unique IF NOT EXISTS
    FOR (fn:Function) REQUIRE fn.qualified_name IS UNIQUE;

// ---------------------------------------------------------------------------
// Additional indexes for common query patterns
// ---------------------------------------------------------------------------

CREATE INDEX file_module_path IF NOT EXISTS
    FOR (f:File) ON (f.module_path);

CREATE INDEX class_name IF NOT EXISTS
    FOR (c:Class) ON (c.name);

CREATE INDEX function_name IF NOT EXISTS
    FOR (fn:Function) ON (fn.name);

CREATE INDEX route_path IF NOT EXISTS
    FOR (r:Route) ON (r.path);

CREATE INDEX route_method IF NOT EXISTS
    FOR (r:Route) ON (r.http_method);

// ---------------------------------------------------------------------------
// New node types: Parameter, Decorator, Import, Docstring
// ---------------------------------------------------------------------------

CREATE CONSTRAINT parameter_qname_unique IF NOT EXISTS
    FOR (p:Parameter) REQUIRE p.qualified_name IS UNIQUE;

CREATE CONSTRAINT decorator_name_unique IF NOT EXISTS
    FOR (d:Decorator) REQUIRE d.name IS UNIQUE;

CREATE CONSTRAINT import_id_unique IF NOT EXISTS
    FOR (i:Import) REQUIRE i.id IS UNIQUE;

CREATE CONSTRAINT docstring_qname_unique IF NOT EXISTS
    FOR (d:Docstring) REQUIRE d.qualified_name IS UNIQUE;

CREATE INDEX parameter_name IF NOT EXISTS
    FOR (p:Parameter) ON (p.name);

CREATE INDEX decorator_name_idx IF NOT EXISTS
    FOR (d:Decorator) ON (d.name);

CREATE INDEX import_module IF NOT EXISTS
    FOR (i:Import) ON (i.module);

// ---------------------------------------------------------------------------
// Full-text indexes for keyword search
// ---------------------------------------------------------------------------

CREATE FULLTEXT INDEX entity_search IF NOT EXISTS
    FOR (n:Class|Function|File)
    ON EACH [n.name, n.docstring, n.qualified_name];

CREATE FULLTEXT INDEX source_search IF NOT EXISTS
    FOR (n:Function)
    ON EACH [n.source, n.docstring];

// ---------------------------------------------------------------------------
// Vector indexes for semantic search (Neo4j 5.15+)
// Embeddings are 1536-dimensional (text-embedding-3-small)
// ---------------------------------------------------------------------------

CREATE VECTOR INDEX function_embeddings IF NOT EXISTS
    FOR (n:Function) ON n.embedding
    OPTIONS {
        indexConfig: {
            `vector.dimensions`: 1536,
            `vector.similarity_function`: 'cosine'
        }
    };

CREATE VECTOR INDEX file_embeddings IF NOT EXISTS
    FOR (n:File) ON n.embedding
    OPTIONS {
        indexConfig: {
            `vector.dimensions`: 1536,
            `vector.similarity_function`: 'cosine'
        }
    };
