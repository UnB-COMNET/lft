# 4G/LTE Cellular Emulation (srsRAN)

LFT integrates with **srsRAN** (an open-source 3GPP software-defined radio suite) to emulate complete 4G/LTE cellular networks within containerized environments.

----

## 1. 4G/LTE System Components

```text
+---------------------+           +----------------------+           +--------------------+
|  EPC (Core Network) | <== S1 ==>|  eNodeB (Base Stn)   | <== RF ==>|  UE (Mobile Term)  |
|  Container: epc     |   veth    |  Container: enb      |    ZMQ    |  Container: ue     |
|                     |           |                      |           |                    |
| - MME (Signaling)   |           | - PHY / MAC / RLC    |           | - USIM Credentials |
| - HSS (Subscriber DB|           | - PDCP / RRC         |           | - NAS / RRC        |
| - SPGW (IP Gateway) |           | - GNU Radio Broker   |           | - TUN Interface    |
+---------------------+           +----------------------+           +--------------------+
```

  * **EPC (Evolved Packet Core)**: Runs `srsepc`, providing Mobility Management Entity (MME), Home Subscriber Server (HSS), and Serving/Packet Gateway (SPGW).
  * **eNodeB (E-UTRAN Node B)**: Runs `srsenb`, implementing the LTE Radio Access Network stack.
  * **UE (User Equipment)**: Runs `srsue`, emulating cellular terminals with dedicated IMSIs and USIM keys.
  * **RF Emulation**: Nodes communicate over **ZeroMQ (ZMQ)** virtual software radio streams instead of physical radio hardware, eliminating RF interference and requiring zero SDR hardware.

----

## 2. Provisioning Users in the EPC

Subscribers must be registered in the EPC database before attaching:
```python
epc.addNewUE(
    ueName="ue1",
    imsi="001010123456780",
    ip="172.16.0.2"
)
```
This automatically updates the EPC subscriber database (`user_db.csv`) with matching IMSI, Ki, and OPc authentication vectors.

----

## 3. Multi-UE Radio Frequency Multiplexing

To emulate multiple UEs communicating with a single eNodeB simultaneously over ZMQ, LFT utilizes a GNU Radio frequency shift broker (`starGnuRadioMultiUE()`):
  1. Each UE transmits and receives on dedicated UDP/ZMQ port pairs.
  2. The GNU Radio broker multiplexes the baseband streams into a combined composite channel for the eNodeB.
  3. Once attached, each UE receives a private IP address and a virtual network TUN interface (`tun_srsue`).

----

## 4. Running a 4G Network Test

Execute the pre-built 4G topology example:
```bash
python3 examples/simple4GTopology.py
```
Verify user attachment from the terminal:
```bash
# Check if UE has received its IP on the cellular TUN interface
docker exec ue1 ifconfig tun_srsue

# Ping the EPC gateway through the LTE radio bearer
docker exec ue1 ping -c 4 172.16.0.1
```
