#!/usr/bin/env bash

################################################################################
# This script is for linting the code of DuoLogSync by using the Pylint tool   #
################################################################################

# Directory containing source code for DuoLogSync
SOURCE_DIR="duologsync"

# Path to the file where the report created by Pylint should be saved
CODE_REPORT_PATH="${SOURCE_DIR}"/codequality.json

# Usage of bash substring expansion (${parameter:-word}) such that if 
# 'parameter' (CI_PROJECT_DIR) does not have a value, 'word' will be used. 
# In this case, 'word' is a git command which returns the root / top-level 
# directory for the current git repository
CI_PROJECT_DIR="${GITHUB_WORKSPACE:-$(git rev-parse --show-toplevel)}"

pylint -f json \
    "${CI_PROJECT_DIR}"/"${SOURCE_DIR}" > \
    "${CI_PROJECT_DIR}"/"${CODE_REPORT_PATH}" || true
