# LFT DokuWiki Documentation Suite

This directory contains the full documentation suite for the **Lightweight Fog Testbed (LFT)** in native **DokuWiki** syntax (`.txt`).

## Directory Structure

```
dokuwiki/
├── sidebar.txt                 # Wiki navigation sidebar
├── start.txt                   # Home / Main index
├── installation.txt            # System requirements and installation
├── architecture.txt            # Core architecture and network primitives
├── api_reference.txt           # Complete API reference
├── sdn_topologies.txt          # Programmable SDN topologies
├── code_examples.txt           # In-depth walkthrough of all 8 examples
├── experiments_benchmarks.txt  # Deployment & network performance benchmarks
├── security_scenario.txt       # UNBCA / CIDDS security intrusion scenario
├── wireless_4g.txt             # 4G/LTE mobile network emulation
├── docker_images.txt           # Technical catalog of Docker images
├── troubleshooting.txt         # Diagnostics and teardown procedures
└── LFT_MASTER_MANUAL.txt       # Unified single-page master manual
```

## Importing into a DokuWiki Server

Copy the `.txt` files into your DokuWiki pages directory:
```bash
sudo cp dokuwiki/*.txt /var/www/dokuwiki/data/pages/lft/
sudo chown -R www-data:www-data /var/www/dokuwiki/data/pages/lft/
```
