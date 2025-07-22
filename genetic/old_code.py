#######################################################
# BORRADOR
    
def insert_node(id):
    # read original file
    with open("network.nod.xml", "r") as f:
        content = f.read()

    # find where to insert before the closing tag
    index = content.rfind("</nodes>")

    # text to insert
    new_node = '  <node id="' + id + '" x="10.0" y="0.0" type="priority" />\n'

    # insert the new node
    content = content[:index] + new_node + content[index:]

    # save modified file
    with open("network.nod.xml", "w") as f:
        f.write(content)

def insert_charging_stations(cs_list):
    # read original file
    with open("infraestructura.add.xml", "r") as f:
        content = f.read()

    # find where to insert before the closing tag
    index = content.rfind("</additional>")

    new_cs_list = ''
    '''
    cs[0] id
    cs[1] lane
    cs[2] startPos
    cs[3] endPos
    cs[4] power
    cs[5] group
    cs[6] chargingPort
    cs[7] allowedPowerOutput
    cs[8] groupPower
    '''
    for cs in cs_list:
        # text to insert
        new_cs_list += (
            '\t<chargingStation id="'+cs[0]+'" lane="'+cs[0]+'" startPos="'+cs[0]+'" endPos="'+cs[0]+'" friendlyPos="true" power="'+cs[0]+'">\n'
            '\t\t<param key="group" value="'+cs[0]+'"/>\n'
            '\t\t<param key="chargingPort" value="'+cs[0]+'"/>\n'
            '\t\t<param key="allowedPowerOutput" value="'+cs[0]+'"/>\n'
            '\t\t<param key="groupPower" value="'+cs[0]+'"/>\n'
            '\t\t<param key="chargeDelay" value="5"/>\n'
            '\t</chargingStation>\n'
        )

    # insert the new node
    content = content[:index] + new_cs_list + content[index:]

    # save modified file
    with open("infraestructura.add.xml", "w") as f:
        f.write(content)

def individual_to_charging_stations(ind, edge_ids):    
    '''
    Each individual has the following structure, taking a solution with 5 charging stations as an example:
    [6, 43, 78, 25, 11] index of the edge (from edge_ids list) where the charging station is located
    '''
    cs_list = []
    for gen in range(0,len(ind.genome)): # iterate over the charging stations (gen = genome column index)
        lane = get_lane(edge_ids[ind.genome[gen]])
        for cp in range(3): # iterate over charging points of each charging station
            # Convert each individual to a charging station xml representation
            cs = [
                edge_ids[ind.genome[gen]] + '_' + cp,  # id
                lane,  # lane
                1.0,  # startPos
                4.0,  # endPos
                150000,  # power
                ind.genome[gen],  # group
                _,  # chargingPort
                150000,  # allowedPowerOutput
                200000  # groupPower
                ]
            cs_list.append(cs)
    return cs_list

def compute_middle_coordinates(edges_file, nodes_file, edge_id):
    # 1. Copiar bloque del edge
    edge_block = get_edge_block(edges_file, edge_id)
    if edge_block is None:
        print(f"No se encontró edge {edge_id}")
        return None, None, None

    # 2. Revisar si tiene shape
    shape_points = extract_shape_coords(edge_block)

    if shape_points:
        # Caso con shape
        xm, ym = compute_middle_point(shape_points)
        return edge_block, xm, ym
    else:
        # Caso sin shape → usar from y to
        node_coords = load_node_coords(nodes_file)
        from_node, to_node = get_edge_nodes(edge_block)

        if from_node is None or to_node is None:
            print("No se pudieron extraer from/to del edge.")
            return None, None, None

        x1, y1 = node_coords[from_node]
        x2, y2 = node_coords[to_node]

        xm = (x1 + x2) / 2
        ym = (y1 + y2) / 2

        return edge_block, xm, ym

def split_edge(edge_id, edges_file, nodes_file):
    # Obtener bloque y coordenadas
    edge_block, xm, ym = compute_middle_coordinates(edges_file, nodes_file, edge_id)
    if edge_block is None:
        print("Error. No se encontró el edge.")
        return

    shape_points = extract_shape_coords(edge_block)
    from_node, to_node = get_edge_nodes(edge_block)

    mid_node_id = f"{edge_id}_mid"

    # preparar nuevos shapes si existían
    new_shape1 = None
    new_shape2 = None

    if shape_points:
        mid_point = (xm, ym)

        # split shape en dos mitades
        n = len(shape_points)
        mid_index = n // 2

        first_half = shape_points[:mid_index+1]
        second_half = shape_points[mid_index:]

        # asegurarnos que mid_point está incluido en ambos lados
        if first_half[-1] != mid_point:
            first_half.append(mid_point)
        if second_half[0] != mid_point:
            second_half.insert(0, mid_point)

        # construir strings shape
        new_shape1 = " ".join(f"{x},{y}" for x, y in first_half)
        new_shape2 = " ".join(f"{x},{y}" for x, y in second_half)

    # Generar edge1
    edge1 = replace_attribute(edge_block, "id", f"{edge_id}_1")
    edge1 = replace_attribute(edge1, "from", from_node)
    edge1 = replace_attribute(edge1, "to", mid_node_id)
    if shape_points:
        edge1 = replace_shape(edge1, new_shape1)
    else:
        # quitar shape si existía
        edge1 = re.sub(r'\s*shape="[^"]*"', '', edge1)

    # Generar edge2
    edge2 = replace_attribute(edge_block, "id", f"{edge_id}_2")
    edge2 = replace_attribute(edge2, "from", mid_node_id)
    edge2 = replace_attribute(edge2, "to", to_node)
    if shape_points:
        edge2 = replace_shape(edge2, new_shape2)
    else:
        # quitar shape si existía
        edge2 = re.sub(r'\s*shape="[^"]*"', '', edge2)

    # leer edges.xml y eliminar edge original
    with open(edges_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    edge_start_re = re.compile(r'<edge\b[^>]*id="' + re.escape(edge_id) + r'"')
    new_lines = []
    skip = False

    for line in lines:
        if not skip:
            if edge_start_re.search(line):
                skip = True
                if '/>' in line or '</edge>' in line:
                    skip = False
            else:
                new_lines.append(line)
        else:
            if '/>' in line or '</edge>' in line:
                skip = False

    # Insertar los dos nuevos edges antes de </edges>
    final_lines = []
    for line in new_lines:
        if line.strip() == "</edges>":
            final_lines.append(edge1)
            final_lines.append(edge2)
        final_lines.append(line)

    with open(edges_file, 'w', encoding='utf-8') as f:
        f.writelines(final_lines)

    # añadir nodo intermedio a nodes.xml
    with open(nodes_file, 'r', encoding='utf-8') as f:
        node_lines = f.readlines()

    new_node_line = f'    <node id="{mid_node_id}" x="{xm}" y="{ym}" />\n'

    new_node_lines = []
    for line in node_lines:
        if line.strip() == "</nodes>":
            new_node_lines.append(new_node_line)
        new_node_lines.append(line)

    with open(nodes_file, 'w', encoding='utf-8') as f:
        f.writelines(new_node_lines)

    print(f"Edge {edge_id} duplicado y partido correctamente.")
    print(f"Nuevo nodo {mid_node_id} insertado en ({xm},{ym}).")

def replace_shape(edge_xml_text, new_shape_str):
    """
    Replaces the shape attribute in an edge XML block with a new shape string.
    """
    shape_re = re.compile(r'shape="[^"]*"')
    if shape_re.search(edge_xml_text):
        return shape_re.sub(f'shape="{new_shape_str}"', edge_xml_text)
    else:
        # shape no existía → añadirlo antes de />
        return edge_xml_text.rstrip('/>\n ') + f' shape="{new_shape_str}" />\n'