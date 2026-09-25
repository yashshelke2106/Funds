"""One module per AMC. Each exposes CONFIG (ParserConfig) and parse(path) -> list[(title, grid)].

A new AMC gets a module here only after a real sample file has been inspected
(project rule 2). The orchestrator refuses folders with no parser.
"""
