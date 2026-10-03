from profissa_lft.host import Host
from profissa_lft.switch import Switch
from profissa_lft.controller import Controller

h1 = Host('h1')
h2 = Host('h2')
s1 = Switch('s1')
c1 = Controller('c1')

h1.instantiate()
h2.instantiate()
s1.instantiate()
c1.instantiate()

h1.connect(s1, "h1s1", "s1h1")
h2.connect(s1, "h2s1", "s1h2")
c1.connect(s1, "c1s1", "s1c1")

h1.setIp('10.0.0.1', 24, "h1s1")
h2.setIp('10.0.0.2', 24, "h2s1")
c1.setIp('10.0.0.3', 24, "c1s1")

c1.initController('10.0.0.3', 9001)
s1.setController('10.0.0.3', 9001)

s1.connectToInternet('10.0.0.4', 24, "s1host", "hosts1")

h1.setDefaultGateway('10.0.0.4', "h1s1")
h2.setDefaultGateway('10.0.0.4', "h2s1")
c1.setDefaultGateway('10.0.0.4', "c1s1")
