# Copyright (C) 2022 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Unmodified lunch() snapshot from ProjectInfinity-X/build, branch 17,
# inspected 2026-10-30. Used to test the upstream argument parser.
function lunch()
{
    if [[ $# -eq 1 && $1 = "--help" ]]; then
        _lunch_usage
        return 0
    fi
    if [[ $# -eq 0 ]]; then
        echo "No target specified. See lunch --help" 1>&2
        return 1
    fi
    if [[ $# -gt 3 ]]; then
        echo "Too many parameters given. See lunch --help" 1>&2
        return 1
    fi

    local product variant

    # Handle the legacy format
    local legacy=$(echo $1 | grep "-")
    if [[ $# -eq 1 && -n $legacy ]]; then
        IFS="-" read -r product variant <<< "$1"
        if [[ -z "$product" ]] || [[ -z "$variant" ]]; then
            echo "Invalid lunch combo: $1" 1>&2
            echo "Valid combos must be of the form <product>-<variant> when using" 1>&2
            echo "the legacy format.  Run 'lunch --help' for usage." 1>&2
            return 1
        fi
    fi

    # Handle the new format.
    if [[ -z $legacy ]]; then
        product=$1
        release=$2
        if [[ -z $release ]]; then
            release=trunk_staging
        fi
        variant=$3
        if [[ -z $variant ]]; then
            variant=eng
        fi
    fi

    # always pick the latest release
    release=$(grep "BUILD_ID" build/make/core/build_id.mk | tail -1 | cut -d '=' -f 2 | cut -d '.' -f 1 | tr '[:upper:]' '[:lower:]')
    export TARGET_RELEASE=$release

    if (echo -n $1 | grep -q -e "^infinity_") ; then
      INFINITY_BUILD=$(echo -n $product | sed -e 's/^infinity_//g')
    else
      INFINITY_BUILD=
    fi
    export INFINITY_BUILD
    INFINITY_DEVICE=$INFINITY_BUILD
    export INFINITY_DEVICE

    # Validate the selection and set all the environment stuff
    _lunch_meat $product $release $variant

    _lunch_store_leftovers $product $release $variant
}
