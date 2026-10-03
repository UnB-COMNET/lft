# Topology settings: ("PoP-Name", num_clients, num_servers)
POPS = (
    ("PoP-ES", 0, 1), ("PoP-MG", 0, 0),
    ("PoP-RJ", 0, 0), ("PoP-SP", 1, 0)
)

ADJACENCY_MATRIX = (
    # ES MG RJ SP
    ( 0, 1, 1, 0), # PoP-ES
    ( 1, 0, 0, 1), # PoP-MG
    ( 1, 0, 0, 1), # PoP-RJ
    ( 0, 1, 1, 0) # PoP-SP
)

CONFIG = {
    "adjacency_matrix": ADJACENCY_MATRIX,
    "pops": POPS,
    "apply_link_properties": True,         
    "randomize_link_properties": False,      
    "throughput": "35mbit",              
    "delay": "10ms",                         
    "jitter": "1ms"          
}
