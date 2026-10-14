"""Distribuição das palavras de uma linha do extrato nas colunas (services.layouts._distribuir)."""
from services.layouts import HISTORICO, IGNORAR, SALDO, VALOR, DATA, _Faixa, _distribuir

# Colunas do extrato Itaú: Data | Lançamentos | Razão Social | CNPJ/CPF | Valor (R$) | Saldo (R$)
FAIXAS = [_Faixa(DATA, False, 30, 55, float("-inf")), _Faixa(HISTORICO, False, 95, 140, 85),
          _Faixa(IGNORAR, False, 260, 320, 250), _Faixa(IGNORAR, False, 390, 440, 380),
          _Faixa(VALOR, True, 470, 510, 460), _Faixa(SALDO, True, 530, 570, 520)]


def _palavra(x0, x1, texto, y=100):
    return (x0, y - 8, x1, y, texto)


def test_numero_no_nome_do_cliente_nao_vira_valor():
    """Itaú 13/10/2026: razão social de uma loja "de 1,99" era lida como o valor do PIX (R$ 1,99 no lugar
    de R$ 2.572,80) e a conferência de saldo da conta falhava."""
    linha = [_palavra(30, 70, "13/10/2026"), _palavra(95, 125, "PIX"), _palavra(128, 165, "RECEBIDO"),
             _palavra(260, 290, "LOJA"), _palavra(293, 318, "MEGA"), _palavra(321, 340, "1,99"),
             _palavra(390, 470, "00.000.000/0001-00"), _palavra(478, 510, "2.572,80")]
    celulas = _distribuir(linha, FAIXAS)
    assert celulas[VALOR] == ["2.572,80"]
    assert "1,99" in celulas[IGNORAR][0]


def test_valores_alinhados_a_direita_continuam_na_coluna_de_valor():
    linha = [_palavra(30, 70, "13/10/2026"), _palavra(95, 140, "TARIFA"),
             _palavra(440, 510, "1.344.494,04"), _palavra(545, 570, "0,00")]
    celulas = _distribuir(linha, FAIXAS)
    assert celulas[VALOR] == ["1.344.494,04"] and celulas[SALDO] == ["0,00"]
