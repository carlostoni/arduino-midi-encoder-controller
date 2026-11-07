# Tampa com painel traseiro a 35 graus - script para Autodesk Fusion
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

MM = 0.1  # Fusion trabalha em cm
c_ = math.cos(math.radians(ANG))
s_ = math.sin(math.radians(ANG))
YB = Y1 - L_INC * c_                 # inicio da rampa (externo)
Z_TOP2 = Z_TOP + L_INC * s_          # topo da parede traseira


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

        # 6) Exporta STEP
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