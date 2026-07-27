---
name: docx
description: >-
  Create, read, edit, and manipulate Word .docx files with document and XML tooling. Use only when the user explicitly requests Word document output or modification; for Cliora documentation content use doc-coauthoring first.
---

# DOCX

Use this skill only for explicit Word file work. Use `doc-coauthoring` first when the task is primarily about Cliora document content.

## Workflow

1. Inspect the input format, requested output, preservation requirements, and available tools.
2. Read [Word workflows](references/word-workflows.md) before creating or editing a document.
3. Use docx-js for new documents and unpack/edit/repack OOXML for precise existing-document changes.
4. Preserve styles, numbering, relationships, comments, tracked changes, images, headers, footers, and section settings not in scope.
5. Work on a copy or explicit output path; never overwrite the only source without clear authorization.
6. Validate package structure, extract text, render representative pages, and inspect the visual result.

Use the bundled scripts for accepting tracked changes and comments where the reference directs. Run helper usage or a representative safe input before relying on a script.
