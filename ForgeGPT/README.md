### ForgeGPT
----
Migrating normal Rust third party libraries into TEE-compatible versions combing RAG technique with LLM-based patch pipeline

## Pipeline Design

This pipeline aims to facilitate repository-level migration for Rust libraries.

The migration is two-fold:
1. Dependency migration -> Use TEE-compatible libraries to replace normal libraries
    * know the current library dependencies
    * know how to map from normal dependencies to TEE-compatible dependencies
2. Code patch -> Replace TEE non-compatible code with TEE-compatible code.
    * consider using common known patterns
    * leverage compiler feedback and RAG in a loop to fix the results

For the fix loop pipeline, 
the challenges are what fix strategies we should use to effectively and efficiently patch the code.
1. Identification of patch location
2. Generation of patch: zero-short LLM / RAG-based few shot LLM
3. Revision or re-generation of the patch

There is also an open question: what kind of patch candidates are high-quality?