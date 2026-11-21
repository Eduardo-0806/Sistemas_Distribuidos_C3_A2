"""
Teste de fumaca da plataforma publicada (so biblioteca padrao, sem pip).

    python deploy/testar_deploy.py https://<gateway>.up.railway.app admin <senha>

Percorre o fluxo inteiro pelo gateway: saude -> 401 sem token -> login ->
predict (fila) -> resultado (worker) -> buscar (vetorial).
Tambem serve para testar local: python deploy/testar_deploy.py http://localhost:8000 admin troque-esta-senha
"""
import json
import sys
import time
import urllib.error
import urllib.request


def chamar(metodo, url, corpo=None, token=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def checar(nome, condicao, detalhe=""):
    print(f"[{'OK' if condicao else 'FALHOU'}] {nome} {detalhe}")
    if not condicao:
        sys.exit(1)


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    base, usuario, senha = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]

    st, _ = chamar("GET", f"{base}/saude")
    checar("GET /saude", st == 200, f"-> {st}")
    if base.startswith("https://"):
        checar("HTTPS", True, "(certificado valido)")

    st, _ = chamar("POST", f"{base}/predict", {"texto": "teste"})
    checar("rota protegida sem token -> 401", st == 401, f"-> {st}")

    st, corpo = chamar("POST", f"{base}/login", {"usuario": usuario, "senha": senha})
    checar("POST /login", st == 200 and "access_token" in corpo, f"-> {st}")
    token = corpo["access_token"]

    st, corpo = chamar("POST", f"{base}/predict", {"texto": "servico excelente"}, token)
    checar("POST /predict -> 202 (na fila)", st == 202 and "id" in corpo, f"-> {st}")
    tarefa = corpo["id"]

    inicio, status = time.time(), None
    while time.time() - inicio < 30:
        st, corpo = chamar("GET", f"{base}/resultado/{tarefa}", token=token)
        status = corpo.get("status")
        if status in ("pronto", "erro"):
            break
        time.sleep(0.5)
    checar("GET /resultado (worker processou)", status == "pronto",
           f"-> {status} {corpo.get('sentimento', '')} "
           f"em {time.time() - inicio:.1f}s")

    st, corpo = chamar("POST", f"{base}/buscar",
                       {"pergunta": "o que diz o teorema CAP?", "top_k": 2}, token)
    checar("POST /buscar (vetorial)", st == 200 and corpo.get("resultados"),
           f"-> {st}, {len(corpo.get('resultados', []))} resultado(s)")

    print("\nTudo certo: a plataforma publicada responde ponta a ponta.")


if __name__ == "__main__":
    main()
