# Tampa com painel traseiro a 35 graus - script para Autodesk Fusion (versao para impressao 3D em PLA)
# Como usar: Utilities > Add-Ins > Scripts and Add-Ins > Create (Python),
# cole este conteudo no arquivo criado, salve e clique em Run.
# O script cria um novo design, monta a peca e exporta Tampa_35graus.step
# para a Area de Trabalho (ou para a pasta do usuario).

import adsk.core, adsk.fusion, traceback, os, math

# ---------------- Parametros (mm) ----------------
X0, X1 = 9.069, 230.769     # largura externa 221,7
Y0, Y1 = 20.0, 184.8        # profundidade externa 164,8 (mantem ~7,9 mm entre botoes e rampa)
Z_BASE = -9.0               # borda inferior da saia
Z_TOP = 4.0                 # topo plano
ESP = 2.0                   # espessura de parede e topo
RAIO_CANTO = 5.0            # raio dos cantos em planta (externo)
RAIO_TOPO = 5.0             # arredondamento das bordas de cima (> ESP)
RAIO_DOBRA = 12.0           # arredondamento da dobra entre topo plano e rampa
ANG = 35.0                  # inclinacao do painel traseiro
L_INC = 45.0                # comprimento da face inclinada (+5 mm)

# Display OLED 1,3" 128x64 (area ativa 29,42 x 14,70) - janela com folga
DISP_W, DISP_H = 31.0, 16.0
DISP_X = 62.0               # centro em X
# Centro exato da parte plana da rampa (descontando a curva da dobra e a da borda de tras)
T_DOBRA = RAIO_DOBRA * math.tan(math.radians(ANG) / 2)        # curva da dobra
T_TOPO = RAIO_TOPO * math.tan(math.radians(90 + ANG) / 2)     # curva da borda de tras
S_CENTRO = (T_DOBRA + (L_INC - T_TOPO)) / 2.0
# Furos do painel inclinado: 5 em linha, no meio da rampa, espacamento igual
GRUPO_X = 158.6             # centro em X dos furos E da matriz de botoes (ficam alinhados)
PASSO = 22.0                # distancia entre furos (alinhado com as colunas de botoes)
FUROS_INC = [(GRUPO_X + (i - 2) * PASSO, S_CENTRO) for i in range(5)]
FURO_INC_D = 7.0

# Fixacao na base: torres com furo para inserto roscado M3 (aplicado a quente)
FIX_POS = [(17.0, 30.0), (222.7, 30.0), (17.0, 140.0), (222.7, 140.0)]  # (x, y)
TORRE_D = 7.0               # diametro da torre
INSERTO_D = 4.0             # furo para inserto M3 (confira o do seu inserto: 4,0-4,2)
INSERTO_PROF = 6.0          # profundidade do furo do inserto

# Suportes para parafusar o display (OLED 1,3") por dentro da rampa
# ATENCAO: meca o seu modulo antes de imprimir e ajuste estes valores
DISPLAY_SUPORTES = True
DISP_FUROS_DX = 30.4        # distancia entre furos da placa, na horizontal
DISP_FUROS_DS = 28.0        # distancia entre furos da placa, ao longo da rampa
DISP_FUROS_OFF = 0.0        # deslocamento do centro dos furos em relacao a janela (ao longo da rampa)
SUP_D, SUP_FURO_D = 5.0, 1.8  # suporte e furo para parafuso M2 autoatarraxante
SUP_H = 2.0                 # altura do suporte (~ espessura do vidro do display)

MM = 0.1  # Fusion trabalha em cm
c_ = math.cos(math.radians(ANG))
s_ = math.sin(math.radians(ANG))
YB = Y1 - L_INC * c_                 # inicio da rampa (externo)
Z_TOP2 = Z_TOP + L_INC * s_          # topo da parede traseira
Z_ENC = -9.0                         # borda de baixo da saia (encosta na base)


def P(x, y, z):
    return adsk.core.Point3D.create(x * MM, y * MM, z * MM)


def ponto_rampa(x, s):
    """Ponto na face externa inclinada: x, distancia s a partir da dobra."""
    return P(x, YB + s * c_, Z_TOP + s * s_)


def poligono(sketch, pts_modelo):
    lines = sketch.sketchCurves.sketchLines
    pts = [sketch.modelToSketchSpace(p) for p in pts_modelo]
    first = prev = None
    n = len(pts)
    for i in range(n):
        a = prev.endSketchPoint if prev else pts[0]
        b = first.startSketchPoint if (i == n - 1) else pts[i + 1]
        ln = lines.addByTwoPoints(a, b)
        if first is None:
            first = ln
        prev = ln


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        root = design.rootComponent
        feats = root.features
        ext = feats.extrudeFeatures
        VI = adsk.core.ValueInput.createByReal

        # 1) Perfil lateral no plano central (YZ deslocado) e extrusao simetrica
        xc = (X0 + X1) / 2.0
        pin = root.constructionPlanes.createInput()
        pin.setByOffset(root.yZConstructionPlane, VI(xc * MM))
        plano_c = root.constructionPlanes.add(pin)
        sk = root.sketches.add(plano_c)
        sk.name = 'Perfil lateral'
        poligono(sk, [P(xc, Y0, Z_BASE), P(xc, Y0, Z_TOP), P(xc, YB, Z_TOP),
                      P(xc, Y1, Z_TOP2), P(xc, Y1, Z_BASE)])
        ei = ext.createInput(sk.profiles.item(0),
                             adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        ei.setSymmetricExtent(VI((X1 - X0) * MM), True)
        body = ext.add(ei).bodies.item(0)
        body.name = 'Tampa'

        # 2) Raio nos 4 cantos verticais
        tol = 1e-4
        cantos = adsk.core.ObjectCollection.create()
        for e in body.edges:
            a, b = e.startVertex.geometry, e.endVertex.geometry
            if abs(a.x - b.x) < tol and abs(a.y - b.y) < tol:
                nx = min(abs(a.x - X0 * MM), abs(a.x - X1 * MM)) < tol
                ny = min(abs(a.y - Y0 * MM), abs(a.y - Y1 * MM)) < tol
                if nx and ny:
                    cantos.add(e)
        fil = feats.filletFeatures
        def arredonda(colecao, raio):
            fi = fil.createInput()
            try:
                fi.edgeSetInputs.addConstantRadiusEdgeSet(colecao, VI(raio * MM), True)
            except Exception:
                fi.addConstantRadiusEdgeSet(colecao, VI(raio * MM), True)
            fil.add(fi)
        arredonda(cantos, RAIO_CANTO)

        # 2b) Dobra suave entre o topo plano e a rampa
        dobra = adsk.core.ObjectCollection.create()
        for e in body.edges:
            a, b = e.startVertex.geometry, e.endVertex.geometry
            if all(abs(v.y - YB * MM) < tol and abs(v.z - Z_TOP * MM) < tol for v in (a, b)):
                dobra.add(e)
        arredonda(dobra, RAIO_DOBRA)

        # 2c) Bordas de cima arredondadas (contorno do topo plano e da rampa)
        def eh_cil_x(face):
            g = face.geometry
            return isinstance(g, adsk.core.Cylinder) and abs(abs(g.axis.x) - 1) < 1e-3
        topos = []
        for f in body.faces:
            g = f.geometry
            if not isinstance(g, adsk.core.Plane):
                continue
            n = g.normal
            plano_topo = abs(abs(n.z) - 1) < 1e-3 and abs(f.centroid.z - Z_TOP * MM) < tol
            rampa = abs(n.x) < 1e-3 and abs(abs(n.y) - s_) < 1e-3 and \
                abs(abs(n.z) - c_) < 1e-3 and n.y * n.z < 0
            if plano_topo or rampa:
                topos.append(f)
        bordas = adsk.core.ObjectCollection.create()
        for f in topos:
            for e in f.edges:
                outra = [x for x in e.faces if x != f]
                if outra and not eh_cil_x(outra[0]) and outra[0] not in topos:
                    bordas.add(e)
        arredonda(bordas, RAIO_TOPO)

        # 3) Casca de 2 mm, aberta embaixo
        fundo = None
        for f in body.faces:
            if isinstance(f.geometry, adsk.core.Plane) and \
                    abs(f.centroid.z - Z_BASE * MM) < tol and \
                    abs(abs(f.geometry.normal.z) - 1) < tol:
                fundo = f
        rem = adsk.core.ObjectCollection.create()
        rem.add(fundo)
        shi = feats.shellFeatures.createInput(rem, False)
        shi.insideThickness = VI(ESP * MM)
        feats.shellFeatures.add(shi)

        # 4) Recortes do topo plano (mesmas posicoes do arquivo original)
        sk2 = root.sketches.add(root.xYConstructionPlane)
        sk2.name = 'Recortes topo plano'
        lines = sk2.sketchCurves.sketchLines
        circs = sk2.sketchCurves.sketchCircles
        def rect(xa, ya, xb, yb):
            lines.addTwoPointRectangle(sk2.modelToSketchSpace(P(xa, ya, 0)),
                                       sk2.modelToSketchSpace(P(xb, yb, 0)))
        for x in [GRUPO_X + (i - 2) * PASSO - 7.0 for i in range(5)]:  # 25 quadrados 14x14, alinhados com os furos
            for y in [38.0, 60.0, 82.0, 104.0, 126.0]:
                rect(x, y, x + 14, y + 14)
        for x in [29.35, 49.35, 69.35, 89.35]:              # 4 rasgos 4x72
            rect(x, 64.0, x + 4, 136.0)
        for i in range(4):                                   # 4 furos D6,7
            circs.addByCenterRadius(sk2.modelToSketchSpace(P(31.35 + 20 * i, 45.0, 0)),
                                    3.35 * MM)
        perfis = adsk.core.ObjectCollection.create()
        for pr in sk2.profiles:
            perfis.add(pr)
        ci = ext.createInput(perfis, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ci.setSymmetricExtent(VI(10 * MM), False)
        ci.participantBodies = [body]
        ext.add(ci)

        # 5) Recortes no painel inclinado (display + 5 furos)
        face_inc, melhor = None, -1e9
        for f in body.faces:
            g = f.geometry
            if isinstance(g, adsk.core.Plane):
                n = g.normal
                # normal da rampa = (0, -sen, cos)
                if abs(n.x) < 1e-3 and abs(abs(n.y) - s_) < 1e-3 and \
                        abs(abs(n.z) - c_) < 1e-3 and n.y * n.z < 0:
                    d = f.centroid.z * c_ - f.centroid.y * s_   # face externa = maior
                    if d > melhor:
                        melhor, face_inc = d, f
        if face_inc is None:
            raise RuntimeError('Face inclinada nao encontrada')
        sk3 = root.sketches.add(face_inc)
        sk3.name = 'Recortes painel inclinado'
        hx, hs = DISP_W / 2.0, DISP_H / 2.0
        poligono(sk3, [ponto_rampa(DISP_X - hx, S_CENTRO - hs),
                       ponto_rampa(DISP_X + hx, S_CENTRO - hs),
                       ponto_rampa(DISP_X + hx, S_CENTRO + hs),
                       ponto_rampa(DISP_X - hx, S_CENTRO + hs)])
        for x, sp in FUROS_INC:
            sk3.sketchCurves.sketchCircles.addByCenterRadius(
                sk3.modelToSketchSpace(ponto_rampa(x, sp)), FURO_INC_D / 2.0 * MM)
        perfis3 = adsk.core.ObjectCollection.create()
        for pr in sk3.profiles:
            if pr.areaProperties().area < 30.0:   # ignora o contorno projetado da face
                perfis3.add(pr)
        ci3 = ext.createInput(perfis3, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ci3.setSymmetricExtent(VI(4 * MM), False)
        ci3.participantBodies = [body]
        ext.add(ci3)

        # 6) Torres para insertos M3 (fixacao na base, parafusos por baixo)
        def novo_corpo(sketch, perfis_col, dist, ref_z_min=None, ref_z_max=None):
            """Extruda como corpo novo; tenta um sentido e, se errado, o outro."""
            for direcao in (adsk.fusion.ExtentDirections.PositiveExtentDirection,
                            adsk.fusion.ExtentDirections.NegativeExtentDirection):
                e = ext.createInput(perfis_col,
                                    adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
                e.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(VI(dist * MM)),
                                   direcao)
                f = ext.add(e)
                bb = f.bodies.item(0).boundingBox
                ok = True
                if ref_z_min is not None and bb.minPoint.z < ref_z_min - tol:
                    ok = False
                if ref_z_max is not None and bb.maxPoint.z > ref_z_max + tol:
                    ok = False
                if ok:
                    return f, direcao
                f.deleteMe()
            raise RuntimeError('Nao foi possivel extrudar no sentido certo')

        def juntar(alvo, corpos):
            col = adsk.core.ObjectCollection.create()
            for b in corpos:
                col.add(b)
            cin = feats.combineFeatures.createInput(alvo, col)
            cin.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
            feats.combineFeatures.add(cin)

        pin3 = root.constructionPlanes.createInput()
        pin3.setByOffset(root.xYConstructionPlane, VI(Z_ENC * MM))
        plano_enc = root.constructionPlanes.add(pin3)
        sk4 = root.sketches.add(plano_enc)
        sk4.name = 'Torres insertos'
        for x, y in FIX_POS:
            sk4.sketchCurves.sketchCircles.addByCenterRadius(
                sk4.modelToSketchSpace(P(x, y, Z_ENC)), TORRE_D / 2.0 * MM)
        col4 = adsk.core.ObjectCollection.create()
        for pr in sk4.profiles:
            col4.add(pr)
        h_torre = (Z_TOP - ESP) - Z_ENC + 0.5      # sobe ate entrar 0,5 mm no topo
        f_t, _ = novo_corpo(sk4, col4, h_torre, ref_z_min=Z_ENC * MM)
        juntar(body, [f_t.bodies.item(j) for j in range(f_t.bodies.count)])
        sk5 = root.sketches.add(plano_enc)
        sk5.name = 'Furos insertos'
        for x, y in FIX_POS:
            sk5.sketchCurves.sketchCircles.addByCenterRadius(
                sk5.modelToSketchSpace(P(x, y, Z_ENC)), INSERTO_D / 2.0 * MM)
        col5 = adsk.core.ObjectCollection.create()
        for pr in sk5.profiles:
            col5.add(pr)
        cf = ext.createInput(col5, adsk.fusion.FeatureOperations.CutFeatureOperation)
        cf.setSymmetricExtent(VI(INSERTO_PROF * MM), False)   # para baixo nao ha material
        cf.participantBodies = [body]
        ext.add(cf)

        # 7) Suportes do display por dentro da rampa
        if DISPLAY_SUPORTES:
            face_int, pior = None, 1e9
            for f in body.faces:
                g = f.geometry
                if isinstance(g, adsk.core.Plane):
                    n = g.normal
                    if abs(n.x) < 1e-3 and abs(abs(n.y) - s_) < 1e-3 and \
                            abs(abs(n.z) - c_) < 1e-3 and n.y * n.z < 0:
                        d = f.centroid.z * c_ - f.centroid.y * s_   # face interna = menor
                        if d < pior:
                            pior, face_int = d, f
            def ponto_int(x, sp):
                return P(x, YB + sp * c_ + ESP * s_, Z_TOP + sp * s_ - ESP * c_)
            sc = S_CENTRO + DISP_FUROS_OFF
            pts_sup = [(DISP_X + dx * DISP_FUROS_DX / 2, sc + ds * DISP_FUROS_DS / 2)
                       for dx in (-1, 1) for ds in (-1, 1)]
            # tubo (suporte com furo) desenhado de uma vez: circulo externo + furo
            sk6 = root.sketches.add(face_int)
            sk6.name = 'Suportes display'
            for x, sp in pts_sup:
                centro = sk6.modelToSketchSpace(ponto_int(x, sp))
                sk6.sketchCurves.sketchCircles.addByCenterRadius(centro, SUP_D / 2.0 * MM)
                sk6.sketchCurves.sketchCircles.addByCenterRadius(centro, SUP_FURO_D / 2.0 * MM)
            area_anel = math.pi * ((SUP_D / 2) ** 2 - (SUP_FURO_D / 2) ** 2) * MM * MM
            col6 = adsk.core.ObjectCollection.create()
            for pr in sk6.profiles:
                if abs(pr.areaProperties().area - area_anel) < 0.3 * area_anel:
                    col6.add(pr)
            # o suporte tem de ir para dentro (para baixo), nunca atravessar o painel
            z_face_max = max(ponto_int(x, sp).z for x, sp in pts_sup) + (SUP_D / 2 * s_ + 0.5) * MM
            f_s, _ = novo_corpo(sk6, col6, SUP_H, ref_z_max=z_face_max)
            juntar(body, [f_s.bodies.item(j) for j in range(f_s.bodies.count)])

        # 8) Exporta STEP
        pasta = os.path.join(os.path.expanduser('~'), 'Desktop')
        if not os.path.isdir(pasta):
            pasta = os.path.expanduser('~')
        caminho = os.path.join(pasta, 'Tampa_35graus.step')
        em = design.exportManager
        em.execute(em.createSTEPExportOptions(caminho, root))
        ui.messageBox('Tampa criada e exportada em:\n' + caminho)
    except Exception:
        if ui:
            ui.messageBox('Erro:\n{}'.format(traceback.format_exc()))