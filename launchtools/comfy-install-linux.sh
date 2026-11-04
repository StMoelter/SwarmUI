#!/usr/bin/env bash

# Check if GPU type is provided
if [ $# -eq 0 ]; then
    >&2 echo "Error: GPU type not specified. Please use 'amd' or 'nv' as an argument."
    exit 1
fi

GPU_TYPE=$1

# Colab must keep its notebook interpreter and preinstalled CUDA stack.
if [ "${SWARM_COLAB_MODE}" == "true" ]; then
    set -e
    if [ "$GPU_TYPE" != "nv" ] || [ ! -x "${SWARM_COLAB_PYTHON}" ] || [ ! -s "${PIP_CONSTRAINT}" ]; then
        >&2 echo "ERROR: Colab requires an NVIDIA GPU, notebook Python, and a constraints file. Run the Colab preparation cell first."
        exit 1
    fi
    export SWARM_NO_VENV=true
    "${SWARM_COLAB_PYTHON}" -s -c "import torch, torchvision; assert torch.cuda.is_available(), 'Select a GPU runtime in Colab before installing SwarmUI.'" || {
        >&2 echo "ERROR: Colab's existing PyTorch/CUDA environment is not usable. Start a fresh GPU runtime."
        exit 1
    }
fi

# Validate GPU type
if [ "$GPU_TYPE" != "amd" ] && [ "$GPU_TYPE" != "nv" ]; then
    >&2 echo "Error: Invalid GPU type. Please use 'amd' or 'nv'."
    exit 1
fi

mkdir -p dlbackend

cd dlbackend

if [ "${SWARM_COLAB_MODE}" == "true" ] && [ -d ComfyUI/.git ]; then
    echo "Reusing the existing ComfyUI checkout."
else
    if [ "${SWARM_COLAB_MODE}" == "true" ]; then
        git clone --depth 1 https://github.com/comfyanonymous/ComfyUI
    else
        git clone https://github.com/comfyanonymous/ComfyUI
    fi
fi

cd ComfyUI

# Try to find a good python executable, and dodge unsupported python versions
if [ "${SWARM_COLAB_MODE}" == "true" ]; then
    python="$SWARM_COLAB_PYTHON"
else
    for pyvers in python3.11 python3.12 python3.10 python3 python
    do
        python=`which $pyvers`
        if [ "$python" != "" ]; then
            break
        fi
    done
fi
if [ "$python" == "" ]; then
    >&2 echo "ERROR: cannot find python3"
    >&2 echo "Please follow the install instructions in the readme!"
    exit 1
fi

# Make and activate the venv. "python3" in the venv is now the python executable.
if [ -z "${SWARM_NO_VENV}" ]; then
    # Validate venv
    venv=`$python -m venv 2>&1`
    case $venv in
        *usage*)
            :
        ;;
        *)
            >&2 echo "ERROR: python venv is not installed"
            >&2 echo "Please follow the install instructions in the readme!"
            >&2 echo "If on Ubuntu/Debian, you may need: sudo apt install python3-venv"
            exit 1
        ;;
    esac

    echo "Making venv..."
    $python -s -m venv venv
    source venv/bin/activate
    python=python3
    python3 -m ensurepip --upgrade
else
    echo "swarm_no_venv set, will not create venv"
fi

# Install PyTorch based on GPU type
if [ "${SWARM_COLAB_MODE}" == "true" ]; then
    echo "Keeping Colab's preinstalled PyTorch and CUDA packages."
elif [ "$GPU_TYPE" == "nv" ]; then
    echo "install nvidia torch..."
    $python -s -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130 --no-cache-dir
elif [ "$GPU_TYPE" == "amd" ]; then
    echo "install amd torch..."
    $python -s -m pip install --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/rocm7.1 --no-cache-dir
fi

echo "install general requirements..."
if ! "$python" -s -m pip install -r requirements.txt; then
    >&2 echo "ERROR: Could not install ComfyUI requirements. In Colab, check the pip conflict above against the protected baseline in PIP_CONSTRAINT."
    exit 1
fi

echo "Installation completed for $GPU_TYPE GPU."
