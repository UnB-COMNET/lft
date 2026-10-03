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

from .base_lft_abstract_factory import BaseLftAbstractFactory
from ..adapters.container.docker_adapter import DockerAdapter
from ..adapters.networking.ip_route_adapter import IpRouteAdapter

class NodeFactory(BaseLftAbstractFactory):
    def createContainerAdapter(self):
        return DockerAdapter()
    
    def createNetworkingAdapter(self):
        return IpRouteAdapter()
    