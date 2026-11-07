# Base inclinada para a Tampa (peca separada) - script para Autodesk Fusion
# Versao para impressao 3D em PLA.
# Como usar: Utilities > Add-Ins > Scripts and Add-Ins > Create (Python),
# cole este conteudo, salve e clique em Run.
# Cria um novo design so com a base e exporta Base_Tampa.step para a Area de Trabalho.
#
# A borda de cima da base encosta na borda de baixo da saia da tampa, e um rebordo
# entra por dentro da saia. Quatro colunas com furo escareado por baixo recebem
# parafusos M3 que vao nos insertos das torres da tampa.
# Imprimir apoiada no fundo, rebordo para cima, sem suporte.

import adsk.core, adsk.fusion, traceback, os, math

# ------------- Medidas da tampa (devem bater com Tampa_35graus.py) -------------
X0, X1 = 9.069, 230.769     # largura externa 221,7
Y0, Y1 = 20.0, 184.8        # profundidade externa 164,8
Z_ENC = -9.0                # borda de baixo da saia da tampa = topo da base
RAIO_CANTO = 5.0            # raio dos cantos da tampa (externo)
ESP_TAMPA = 2.0             # espessura da saia da tampa
FIX_POS = [(17.0, 30.0), (222.7, 30.0), (17.0, 140.0), (222.7, 140.0)]  # torres da tampa

# ---------------- Base ----------------
H_TRAS = 50.0               # altura da base atras (parte mais alta)
H_FRENTE = 20.0             # altura da base na frente (define o angulo)
ESP_BASE = 2.5              # parede e fundo da base
# Rebordo de encaixe (entra por dentro da saia da tampa)
FOLGA = 0.3                 # folga por lado entre rebordo e saia (FDM/PLA)
LIP_H = 5.0                 # altura do rebordo acima da base
LIP_E = 1.8                 # espessura do rebordo
LIP_REFORCO = 6.0           # o rebordo continua para baixo, colado na parede (apoio)
# Colunas dos parafusos M3 (entram por baixo)
COL_D = 8.0                 # diametro da coluna
FURO_M3 = 3.4               # furo passante do parafuso
ESCAREADO_D = 6.5           # alojamento da cabeca do parafuso
CARNE = 5.0                 # material deixado no topo da coluna (parafuso M3x10)

MM = 0.1  # Fusion trabalha em cm
ANG_BASE = math.degrees(math.atan((H_TRAS - H_FRENTE) / (Y1 - Y0)))


def P(x, y, z):
    return adsk.core.Point3D.create(x * MM, y * MM, z * MM)


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
        DIRS = (adsk.fusion.ExtentDirections.PositiveExtentDirection,
                adsk.fusion.ExtentDirections.NegativeExtentDirection)
        tol = 1e-4

        def arredonda(colecao, raio):
            fil = feats.filletFeatures
            fi = fil.createInput()
            try:
                fi.edgeSetInputs.addConstantRadiusEdgeSet(colecao, VI(raio * MM), True)
            except Exception:
                fi.addConstantRadiusEdgeSet(colecao, VI(raio * MM), True)
            fil.add(fi)

        def cantos_verticais(body, xa, xb, ya, yb):
            col = adsk.core.ObjectCollection.create()
            for e in body.edges:
                a, b = e.startVertex.geometry, e.endVertex.geometry
                if abs(a.x - b.x) < tol and abs(a.y - b.y) < tol:
                    nx = min(abs(a.x - xa * MM), abs(a.x - xb * MM)) < tol
                    ny = min(abs(a.y - ya * MM), abs(a.y - yb * MM)) < tol
                    if nx and ny:
                        col.add(e)
            return col

        def faces_horizontais(body, zs):
            col = adsk.core.ObjectCollection.create()
            for f in body.faces:
                g = f.geometry
                if isinstance(g, adsk.core.Plane) and abs(abs(g.normal.z) - 1) < 1e-6:
                    if any(abs(f.centroid.z - z * MM) < tol for z in zs):
                        col.add(f)
            return col

        def casca(body, faces, esp):
            si = feats.shellFeatures.createInput(faces, False)
            si.insideThickness = VI(esp * MM)
            feats.shellFeatures.add(si)

        def plano_z(z):
            pi = root.constructionPlanes.createInput()
            pi.setByOffset(root.xYConstructionPlane, VI(z * MM))
            return root.constructionPlanes.add(pi)

        def perfis(sketch, area_max=None):
            col = adsk.core.ObjectCollection.create()
            for pr in sketch.profiles:
                if area_max is None or pr.areaProperties().area < area_max:
                    col.add(pr)
            return col

        def circulos(plano, raio, z, nome):
            sk = root.sketches.add(plano)
            sk.name = nome
            for x, y in FIX_POS:
                sk.sketchCurves.sketchCircles.addByCenterRadius(
                    sk.modelToSketchSpace(P(x, y, z)), raio * MM)
            return sk

        def juntar(alvo, corpos):
            col = adsk.core.ObjectCollection.create()
            for b in corpos:
                col.add(b)
            cin = feats.combineFeatures.createInput(alvo, col)
            cin.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
            feats.combineFeatures.add(cin)

        # 1) Corpo da base: perfil em cunha extrudado na largura
        xc = (X0 + X1) / 2.0
        pin = root.constructionPlanes.createInput()
        pin.setByOffset(root.yZConstructionPlane, VI(xc * MM))
        sk = root.sketches.add(root.constructionPlanes.add(pin))
        sk.name = 'Perfil base'
        poligono(sk, [P(xc, Y0, Z_ENC), P(xc, Y1, Z_ENC),
                      P(xc, Y1, Z_ENC - H_TRAS), P(xc, Y0, Z_ENC - H_FRENTE)])
        ei = ext.createInput(sk.profiles.item(0),
                             adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        ei.setSymmetricExtent(VI((X1 - X0) * MM), True)
        base = ext.add(ei).bodies.item(0)
        base.name = 'Base'

        # 2) Cantos iguais aos da tampa e casca aberta em cima
        arredonda(cantos_verticais(base, X0, X1, Y0, Y1), RAIO_CANTO)
        casca(base, faces_horizontais(base, [Z_ENC]), ESP_BASE)

        # face de baixo (apoio na mesa) = a de menor altura
        fundo = min([f for f in base.faces if isinstance(f.geometry, adsk.core.Plane)],
                    key=lambda f: f.centroid.z)

        # 3) Rebordo: anel que sobe LIP_H acima da base e desce LIP_REFORCO colado na parede
        lx0, lx1 = X0 + ESP_TAMPA + FOLGA, X1 - ESP_TAMPA - FOLGA
        ly0, ly1 = Y0 + ESP_TAMPA + FOLGA, Y1 - ESP_TAMPA - FOLGA
        r_lip = max(RAIO_CANTO - ESP_TAMPA - FOLGA, 0.5)
        z_lip0 = Z_ENC - LIP_REFORCO
        z_lip1 = Z_ENC + LIP_H
        sk2 = root.sketches.add(plano_z(z_lip0))
        sk2.name = 'Rebordo'
        sk2.sketchCurves.sketchLines.addTwoPointRectangle(
            sk2.modelToSketchSpace(P(lx0, ly0, z_lip0)),
            sk2.modelToSketchSpace(P(lx1, ly1, z_lip0)))
        lip = None
        for d in DIRS:
            e = ext.createInput(sk2.profiles.item(0),
                                adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            e.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(
                VI((z_lip1 - z_lip0) * MM)), d)
            f = ext.add(e)
            if f.bodies.item(0).boundingBox.maxPoint.z > (z_lip1 - 0.5) * MM:
                lip = f.bodies.item(0)
                break
            f.deleteMe()
        arredonda(cantos_verticais(lip, lx0, lx1, ly0, ly1), r_lip)
        casca(lip, faces_horizontais(lip, [z_lip0, z_lip1]), LIP_E)
        juntar(base, [lip])

        # 4) Colunas dos parafusos: do topo da base ate o fundo
        plano_enc = plano_z(Z_ENC)
        sk3 = circulos(plano_enc, COL_D / 2.0, Z_ENC, 'Colunas')
        cols = None
        for d in DIRS:
            try:
                e = ext.createInput(perfis(sk3),
                                    adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
                e.setOneSideExtent(adsk.fusion.ToEntityExtentDefinition.create(fundo, False), d)
                f = ext.add(e)
            except Exception:
                continue
            if f.bodies.item(0).boundingBox.minPoint.z < (Z_ENC - 5) * MM:
                cols = [f.bodies.item(j) for j in range(f.bodies.count)]
                break
            f.deleteMe()
        if cols is None:
            raise RuntimeError('Nao foi possivel criar as colunas')
        juntar(base, cols)

        # 5) Furo passante M3
        sk4 = circulos(plano_enc, FURO_M3 / 2.0, Z_ENC, 'Furos M3')
        c4 = ext.createInput(perfis(sk4), adsk.fusion.FeatureOperations.CutFeatureOperation)
        c4.setTwoSidesExtent(adsk.fusion.ThroughAllExtentDefinition.create(),
                             adsk.fusion.ThroughAllExtentDefinition.create())
        c4.participantBodies = [base]
        ext.add(c4)

        # 6) Alojamento da cabeca, por baixo, deixando CARNE mm no topo da coluna
        z_esc = Z_ENC - CARNE
        sk5 = circulos(plano_z(z_esc), ESCAREADO_D / 2.0, z_esc, 'Alojamento cabeca')
        r_teste = (FURO_M3 + ESCAREADO_D) / 4.0       # ponto entre o furo e o alojamento
        x_t, y_t = FIX_POS[0]
        ponto_cima = P(x_t + r_teste, y_t, z_esc + CARNE / 2.0)
        for d in DIRS:
            c5 = ext.createInput(perfis(sk5), adsk.fusion.FeatureOperations.CutFeatureOperation)
            c5.setOneSideExtent(adsk.fusion.ThroughAllExtentDefinition.create(), d)
            c5.participantBodies = [base]
            f = ext.add(c5)
            # se cortou para cima (topo da coluna sumiu), desfaz e corta para baixo
            if base.pointContainment(ponto_cima) == adsk.fusion.PointContainment.PointInsidePointContainment:
                break
            f.deleteMe()

        # 7) Exporta STEP
        pasta = os.path.join(os.path.expanduser('~'), 'Desktop')
        if not os.path.isdir(pasta):
            pasta = os.path.expanduser('~')
        caminho = os.path.join(pasta, 'Base_Tampa.step')
        em = design.exportManager
        em.execute(em.createSTEPExportOptions(caminho, root))
        ui.messageBox('Base criada (inclinacao {:.1f} graus) e exportada em:\n{}'
                      .format(ANG_BASE, caminho))
    except Exception:
        if ui:
            ui.messageBox('Erro:\n{}'.format(traceback.format_exc()))