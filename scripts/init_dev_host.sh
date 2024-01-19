#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2016-2023 OKTET Labs Ltd. All rights reserved.
#
# Initialise host to run bublik development version (from Git).
#

set -e

QUIET=false
ASK=true
BUBLIK_USER=bublik
BUBLIK_HOME_PREFIX=/opt
BUBLIK_GIT="https://github.com/ts-factory/bublik.git"
BUBLIK_UI_GIT="https://github.com/ts-factory/bublik-ui.git"
BUBLIK_CONF_GIT="https://github.com/ts-factory/ts-rigs-sample.git"
TE_GIT="https://github.com/ts-factory/test-environment.git"
DB_PASSWORD="EujUmUk3Ot"
SSH_PUB="${HOME}/.ssh/id_rsa.pub"
OPTS=()


function usage () {
	local msg="$*"

	test -z "$msg" || echo $msg >&2
	cat <<- END_OF_USAGE
	usage: $(basename $0) [-h] [-H db-host] [options] host

	Initialise Bublik development environment on the host.
	See help for all options description.

	END_OF_USAGE
	test -z "$msg" || exit 1
}

function print_help () {
	usage
	cat <<- END_OF_HELP
	options:
	    -h                  show this help
	    -q                  be quiet and do all steps without asking
	    -y                  do all steps without asking
	    -c config           configuration variant to use
	    -u user             system user to run bublik
	                        (default is ${BUBLIK_USER})
	    -d home             bublik user home directory
	                        (default is ${BUBLIK_HOME_PREFIX}/\$user)
	    -b bublik-git-url   bublik Git repository URL
	    -B bublik-ui-url    bublik UI Git repository URL
	    -C bublik-conf-url  bublik configuration Git repository URL
	    -T te-git-url       OKTET Labs Test Environment Git repo URL
	    -i ssh-key          SSH key to use (default is ${SSH_PUB:-unspecified})
	    -k keytab           Optional Kerberos auth keytab to get logs
	                        on runs import. The file should be already
	                        located on target host, e.g. /etc/bublik.keytab
	END_OF_HELP
}

function step() {
	$QUIET && return 0
	echo -n "STEP: $@"
	result=0
	$ASK && while true ; do read -p ' [Yn] ' yn
		case $yn in
			""|[Yy]*) result=0 ; break ;;
			[Nn]*) result=1 ; break ;;
			*) echo "Please answer yes or no." ;;
		esac
	done
	return $result
}

while getopts "hqyc:u:d:i:b:B:C:T:a:k:p:s:F:N:U:W:H:P:" OPTION; do
	case $OPTION in
		h) print_help ; exit ;;
		q) QUIET=true ;;
		y) ASK=false ;;
		c) CONFIG_TO_USE=${OPTARG} ;;
		u) BUBLIK_USER=${OPTARG} ;;
		d) BUBLIK_HOME=${OPTARG} ;;
		i) SSH_PUB=${OPTARG} ;;
		b) BUBLIK_GIT=${OPTARG} ;;
		B) BUBLIK_UI_GIT=${OPTARG} ;;
		C) BUBLIK_CONF_GIT=${OPTARG} ;;
		T) TE_GIT=${OPTARG} ;;
		k) LOGS_KEYTAB=${OPTARG} ;;
		W) DB_PASSWORD="${OPTARG}" ;;
		a | p | s | F | N | U | H | P)
			OPTS+=(-${OPTION} "${OPTARG}")
			;;
		?) usage ; exit 1 ;;
	esac
done
shift $(($OPTIND - 1))

OPTS+=(-u "${BUBLIK_USER}" -W "${DB_PASSWORD}")

# Check if default SSH key exists
test -r "${SSH_PUB}" || {
  step "You need to have '${HOME}/.ssh/id_rsa.pub' or
if you have it stored in a different place, please, spesify it using -i option.
Continuing you must be sure you have access rights to the server." ||
  exit 1
}

test -n "${CONFIG_TO_USE}" || usage "Config to use is unspecified"
OPTS+=(-c "${CONFIG_TO_USE}")

BUBLIK_HOST=$1
test -n "${BUBLIK_HOST}" || usage "Host is unspecified"

shift
test -z "$1" || usage "Extra options specified: $*"

test -n "${BUBLIK_HOME}" || BUBLIK_HOME="${BUBLIK_HOME_PREFIX}/${BUBLIK_USER}"

test -z "${LOGS_KEYTAB}" || OPTS+=(-k "${LOGS_KEYTAB}")

# End of options processing

if test -n "${SSH_PUB}" ; then
	step "Add SSH key ${SSH_PUB} to root@${BUBLIK_HOST}" &&
	ssh-copy-id -i "${SSH_PUB}" "root@${BUBLIK_HOST}"
fi

step "Install packages required for initial bootstrap" &&
ssh -t "root@${BUBLIK_HOST}" apt install sudo git bash

step "Create dedicated system user ${BUBLIK_USER}" &&
ssh "root@${BUBLIK_HOST}" "
	adduser --system --group --shell /bin/bash --home \"${BUBLIK_HOME}\" \
	\"${BUBLIK_USER}\"
	"

step "Grant ${BUBLIK_USER} user sudo required for initial bootstrapping" &&
ssh "root@${BUBLIK_HOST}" "
	echo \"${BUBLIK_USER}\" 'ALL=(ALL) NOPASSWD: ALL' \
		>/etc/sudoers.d/\"${BUBLIK_USER}\"
	"

if test -n "${SSH_PUB}" ; then
	step "Setup SSH access to ${BUBLIK_USER}@${BUBLIK_HOST}" &&
	cat "${SSH_PUB}" | ssh "root@${BUBLIK_HOST}" "
	set -e
	export SSH_DIR=\"${BUBLIK_HOME}\"/.ssh
	mkdir --parents --mode=0700 \"\${SSH_DIR}\"
	export AUTH_KEYS=\"\${SSH_DIR}\"/authorized_keys
	cat >>\"\${AUTH_KEYS}\"
	chmod 0600 \"\${AUTH_KEYS}\"
	chown -R \"${BUBLIK_USER}\":\"${BUBLIK_USER}\" \"\${SSH_DIR}\"
	"
fi

if test -n "${TE_GIT}" ; then
	step "Clone OKTET Labs Test Environment and build tool
You can continue if you have TE access rights" &&
	ssh -t "${BUBLIK_USER}@${BUBLIK_HOST}" "
	set -e
	sudo apt -y install build-essential automake autoconf libtool \
		libpopt-dev libxml2-dev flex bison libssl-dev libglib2.0-dev \
		libjansson-dev libyaml-dev libcurl4-openssl-dev meson
	git clone ${TE_GIT} te
	cd te
	./dispatcher.sh -q --conf-builder=builder.conf.tools --no-run
	"
fi

if test -n "${BUBLIK_GIT}" ; then
	step "Clone Bublik Git repo ${BUBLIK_GIT}" &&
	ssh -t "${BUBLIK_USER}@${BUBLIK_HOST}" "git clone ${BUBLIK_GIT} bublik"
fi

if test -n "${BUBLIK_UI_GIT}" ; then
	step "Clone Bublik UI Git repo ${BUBLIK_UI_GIT}" &&
	ssh -t "${BUBLIK_USER}@${BUBLIK_HOST}" "git clone ${BUBLIK_UI_GIT} bublik-ui"
fi

if test -n "${BUBLIK_CONF_GIT}" ; then
	step "Clone Bublik configurations Git repo ${BUBLIK_CONF_GIT}" &&
	ssh -t "${BUBLIK_USER}@${BUBLIK_HOST}" "git clone ${BUBLIK_CONF_GIT} bublik-conf"
fi

if test -n "${LOGS_KEYTAB}" ; then
	step "Change owner of ${LOGS_KEYTAB} to ${BUBLIK_USER} user" &&
	ssh -t "${BUBLIK_USER}@${BUBLIK_HOST}" "
	sudo chown \"${BUBLIK_USER}\" \"${LOGS_KEYTAB}\"
	"
fi

# Deploy script should accept --logs-keytab option and use the keytab
# to acquire Kerberos ticket which is used to get logs when session
# is imported. It is optional and no kerberos auth will be used
# if a keytab is not provided.

step "Run Bublik deploy script" &&
ssh -t "${BUBLIK_USER}@${BUBLIK_HOST}" ./bublik/scripts/deploy "${OPTS[@]}"

step "Purge Bublik user sudo rights" &&
ssh "root@${BUBLIK_HOST}" "rm -f /etc/sudoers.d/\"${BUBLIK_USER}\""
