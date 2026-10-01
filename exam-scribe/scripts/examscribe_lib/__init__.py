"""ExamScribe: turn textbooks into verified exam-prep materials.

The package is split by pipeline stage. `pipeline.py` is the state machine that
tells the model what to do next; every other module is a deterministic helper
the pipeline (or the CLI in ../examscribe.py) calls.
"""
