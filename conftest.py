# Empty on purpose: pytest adds this file's directory (the project root) to
# sys.path when it collects tests, which is what lets test files do
# `from pipeline.transform import ...` / `from quality.validation_rules import ...`
# etc. - the same "run as a module from project root" convention every
# other script in this project already follows (python -m pipeline.transform).
