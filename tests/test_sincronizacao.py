"""Status da sincronização mostrado na tela (o .bat grava logs/sincronizacao_status.txt)."""
from api.routers.sincronizacao import ler_status


def test_status_ok_erro_e_sem_repositorio(tmp_path):
    assert ler_status(tmp_path)["ligado"] is False
    (tmp_path / ".git-dados").mkdir()
    (tmp_path / "logs").mkdir()
    assert ler_status(tmp_path)["estado"] == ""  # ainda não rodou com a versão nova
    arq = tmp_path / "logs" / "sincronizacao_status.txt"
    arq.write_text("OK|13/11/2026  7:02|Dados enviados e recebidos. \r\n", encoding="cp1252")
    s = ler_status(tmp_path)
    assert (s["estado"], s["quando"], s["mensagem"]) == ("OK", "13/11/2026  7:02", "Dados enviados e recebidos.")
    arq.write_text("ERRO|13/11/2026 21:10|Nao consegui baixar os dados da nuvem (internet).\r\n", encoding="cp1252")
    assert ler_status(tmp_path)["estado"] == "ERRO"
