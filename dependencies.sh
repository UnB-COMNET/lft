#!/usr/bin/env bash
#
# dependencies.sh — único script de instalação do LFT. Um comando, do zero
# a pronto para rodar experimentos: pacotes de sistema (Docker, Open vSwitch,
# ferramentas de rede), o pacote Python (venv + `pip install -e .`, versões
# pinadas em setup.py) e as imagens Docker que os experimentos ONOS
# precisam (ONOS, OVS, iperf).
#
# Uso (a partir da raiz deste repositório, já clonado):
#   chmod +x dependencies.sh
#   sudo ./dependencies.sh
#
# Reexecução: idempotente — rodar de novo não quebra nada, só pula o que já
# está feito.
#
# Testado em: Ubuntu Server 25.04 (Plucky Puffin). Em outras distros/versões,
# os pins de versão abaixo tendem a não existir no repositório: o script cai
# para a versão mais recente disponível e avisa, mas não trava.

set -Eeuo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Rode como root (sudo ./dependencies.sh)" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Log único: sobrescrito a cada execução (não acumula entre rodadas), e
# ainda aparece no terminal (tee), não só no arquivo.
LOG_FILE="$SCRIPT_DIR/dependencies.log"
exec > >(tee "$LOG_FILE") 2>&1
echo "Log desta instalação em: $LOG_FILE"

# ============================================================
# Versões validadas em 2026-08-29 (mesma VM de experimentos do grupo,
# ver infra/setup.sh do projeto PIBIC). Cada uma tenta instalar essa versão
# exata; se o repositório já reciclou essa versão (comum em pacotes do apt,
# ao contrário do PyPI), cai para a mais recente disponível.
# ============================================================
PIN_IPROUTE2="${PIN_IPROUTE2:-6.19.0-1ubuntu1.1}"
PIN_IPTABLES="${PIN_IPTABLES:-1.8.11-2ubuntu3}"
PIN_FIREWALLD="${PIN_FIREWALLD:-2.3.1-3}"
PIN_NFDUMP="${PIN_NFDUMP:-1.7.6-1}"
PIN_OVS="${PIN_OVS:-3.7.1-2}"
PIN_DOCKER_CE="${PIN_DOCKER_CE:-5:29.7.2-1~ubuntu.26.04~resolute}"
PIN_DOCKER_CE_CLI="${PIN_DOCKER_CE_CLI:-5:29.7.2-1~ubuntu.26.04~resolute}"
PIN_DOCKER_COMPOSE_PLUGIN="${PIN_DOCKER_COMPOSE_PLUGIN:-5.5.0-1~ubuntu.26.04~resolute}"

log()  { echo -e "\n[LFT-DEPS] $*"; }
warn() { echo -e "\n[AVISO] $*" >&2; }

apt_install_pinned() {
    # $1 = pacote, $2 = versão exata do apt (dpkg-style). Vazio em $2 = mais recente.
    local pkg="$1" ver="$2"
    if [ -n "$ver" ] && apt-cache madison "$pkg" 2>/dev/null \
        | awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2}' | grep -qx "$ver"; then
        apt-get install -y "${pkg}=${ver}"
    else
        [ -n "$ver" ] && warn "Versão $ver de '$pkg' não está no repositório atual — instalando a mais recente disponível."
        apt-get install -y "$pkg"
    fi
}

log "Atualizando índices do apt"
apt-get update

log "Instalando Docker CE + Compose plugin (repositório oficial da Docker)"
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt_install_pinned docker-ce "$PIN_DOCKER_CE"
apt_install_pinned docker-ce-cli "$PIN_DOCKER_CE_CLI"
apt-get install -y containerd.io docker-buildx-plugin
apt_install_pinned docker-compose-plugin "$PIN_DOCKER_COMPOSE_PLUGIN"
systemctl enable --now docker
if ! getent group docker >/dev/null; then groupadd docker; fi
usermod -aG "docker" "${SUDO_USER:-$USER}"
log "Usuário '${SUDO_USER:-$USER}' adicionado ao grupo 'docker' — precisa de novo login (ou 'newgrp docker') para rodar 'docker' sem sudo."

log "Instalando Open vSwitch"
apt_install_pinned openvswitch-switch "$PIN_OVS"
apt-mark hold openvswitch-switch
systemctl enable --now openvswitch-switch
# Pré-carrega o módulo de kernel e garante que ele suba sozinho em todo boot
# futuro — evita a corrida "ovsdb-server ainda não subiu" na primeira execução.
modprobe openvswitch
echo "openvswitch" | tee /etc/modules-load.d/openvswitch.conf >/dev/null

log "Instalando iproute2 e iptables"
apt_install_pinned iproute2 "$PIN_IPROUTE2"
apt_install_pinned iptables "$PIN_IPTABLES"

log "Instalando Python 3, pip, venv"
apt-get install -y python3 python3-pip python3-venv python-is-python3

log "Instalando firewalld (sem habilitar — conflita com as regras de iptables do Docker)"
apt_install_pinned firewalld "$PIN_FIREWALLD"
systemctl disable --now firewalld 2>/dev/null || true

log "Instalando nfdump"
apt_install_pinned nfdump "$PIN_NFDUMP"

log "Instalando git e tmux"
apt-get install -y git tmux

log "Criando venv e instalando o pacote (versões pinadas em setup.py)"
cd "$SCRIPT_DIR"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

log "Baixando imagem ONOS 2.5.0"
docker pull onosproject/onos:2.5.0

log "Buildando imagens Docker do LFT (openvswitch, iperf)"
docker build -t alexandremitsurukaihara/lst2.0:openvswitch docker/openswitch
docker build -t lft-iperf docker/iperf

log "Pronto. Rodar um experimento:"
echo "  sudo $SCRIPT_DIR/.venv/bin/lft experiment diamond --mode fwd --hindering degrade --run-name teste-01"
