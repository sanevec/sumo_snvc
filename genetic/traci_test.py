from utils import *

if __name__ == "__main__":
    print(obtain_edge_ids())
    print(get_edge_nodes("e7"))
    old = get_edge_block("e7")
    print(old)
    new = replace_attribute(old, "speed", "20.0")
    print(new)
    replace_xml_block_in_file("cs_example/network.edg.xml", old, new)
    print(load_nodes())
    #add_charging_stations([6,7])
    build_world()