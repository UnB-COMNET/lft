# Copyright (C) 2024 Alexandre Mitsuru Kaihara
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

# This file is for defining a package in Python
from setuptools import setup, find_packages

setup(
    name='profissa_lft',
    version='1.0.10',
    packages=find_packages(),
    py_modules=['cli'],
    install_requires=[
        'pandas==3.0.5',
        # <4.0: o ONOS 2.5.0 embute um Karaf SSHD antigo (~2019) que só
        # oferece "ssh-rsa" como host key. paramiko 5.0.0 removeu esse
        # suporte de propósito, sem jeito suportado de reabilitar.
        'paramiko==3.5.1',
        'requests==2.34.2',
        'rich==15.0.0',
        'click==8.5.0',
        # flask/networkx: sem validação de versão exata ainda (as pinadas
        # acima foram testadas na VM de experimentos do grupo, ver
        # infra/setup.sh do projeto PIBIC). Ajustar ao validar.
        'flask>=3.0',
        'networkx>=3.0',
    ],
    entry_points={
        'console_scripts': [
            'lft=cli:main',
        ],
    },
    author='Alexandre Mitsuru Kaihara',
    author_email='alexandreamk1@gmail.com',
    description='LFT is a framework designed to facilitate the creation of lightweight network topologies with ease. Using Docker containers, it is possible to add any container to the network to provide network services or even emulate network devices, such as switches, controllers (in Software Defined Networking). This project has integration with OpenvSwitch to emulate the network forwarding devices and srsRAN 4G to emulate wireless links for Fog and Edge application scenarios.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/alexandrekaihara/lft    ',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.9',
    include_package_data=True,
    package_data={'onos_topologies': ['README.md', 'assets/onos_apps/*.oar',
                                     'assets/certs/*.pem', 'assets/dashboards/*.pbix']},
)

