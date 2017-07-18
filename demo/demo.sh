#!/bin/bash

NUM_DEVICES=${NUM_DEVICES:-3}

IMAGE="fcr-host-device"

DEVICES=($(seq -f 'dev-%03G' 1 "$NUM_DEVICES"))

function build() {
    docker build -t fcr-host-device device
}

function startup() {
    for dev in "${DEVICES[@]}"; do
        docker run -h "$dev" --name "$dev" -d "$IMAGE"
    done
}

function create_venv() {
    rm -rf venv

    python3 -m venv venv
    # Activate the virtual env
    # shellcheck disable=1091
    source venv/bin/activate

    pushd ..
    pip install -r requirements.txt
    pip install .
    popd

    pip install -r requirements.txt
}

function setup() {
    # A shortcut to create venv, build docker image, and start docker containers
    cleanup
    create_venv
    build
    startup
}

function cleanup() {
    containers=($(docker ps --filter=ancestor="$IMAGE" -aq))
    docker stop "${containers[@]}"
    docker rm "${containers[@]}"
}

function cli() {
    # shellcheck disable=1091
    source venv/bin/activate
    python3 ../bin/fcr-cli.py "${DEVICES[@]}"
}

function service() {
    # shellcheck disable=1091
    source venv/bin/activate
    python3 fcr_service.py --device_vendors device_vendors.json
}

function usage() {
    cat <<EOT

  $0 {setup | service | cli | cleanup}

  $0 setup

    Create the initial setup
    * creates a virtual env
    * build a docker image
    * Start docker containers

  $0 service

    Start a FCR service

  $0 cli

    Start FCR cli

  $0 cleanup

    Stop and remove docker containers

EOT
}


if [ $# -eq 0 ]; then
    usage
else

    for cmd in "$@"; do
        $cmd
    done

fi
