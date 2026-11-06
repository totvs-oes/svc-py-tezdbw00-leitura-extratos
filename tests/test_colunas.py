"""Distribuição das palavras de uma linha do extrato nas colunas (services.layouts._distribuir)."""
from services.layouts import DATA, HISTORICO, IGNORAR, LAYOUTS, SALDO, VALOR, _Faixa, _distribuir, extrair_com_layout

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


def _linha(y, *celulas):
    return [(x0, y - 8, x0 + 6 * len(texto), y, texto) for x0, texto in celulas]


CABECALHO_ITAU = ((35, "Data"), (84, "Lançamentos"), (221, "Razão"), (260, "Social"), (357, "CNPJ/CPF"),
                  (470, "Valor"), (500, "(R$)"), (530, "Saldo"), (560, "(R$)"))


def _ler_itau(paginas):
    layout = next(l for l in LAYOUTS if l.nome == "Itaú")
    return extrair_com_layout(paginas, layout, "ITAU Conta 6896-9", "2026").lancamentos


def test_historico_cortado_pela_virada_de_pagina_e_emendado():
    """Itaú 06/11/2026: "TED RECEBIDA 104.4266.AEROFLEX" no rodapé e "I" + valor no topo da página seguinte: chegava
    só "I" e a TED da Caixa (R$ 700.000,00) não virava transferência."""
    lancamentos = _ler_itau([
        [_linha(20, *CABECALHO_ITAU),
         _linha(779, (35, "05/11/2026"), (84, "TEG"), (101, "EX"), (113, "GAR"), (475, "804,45")),
         _linha(791, (84, "TED"), (102, "RECEBIDA"), (141, "104.4266.AEROFLEX"))],
        [_linha(27, (35, "05/11/2026"), (84, "I"), (221, "AEROFLEX"), (357, "07.872.967/0001-02"), (462, "700.000,00"))],
    ])
    assert [(l.historico, l.valor) for l in lancamentos] == [
        ("TEG EX GAR", 804.45), ("TED RECEBIDA 104.4266.AEROFLEX I", 700000.0)]


def test_linha_sem_valor_no_meio_da_pagina_nao_emenda_no_lancamento_seguinte():
    lancamentos = _ler_itau([
        [_linha(20, *CABECALHO_ITAU),
         _linha(100, (84, "TEXTO"), (102, "SOLTO")),
         _linha(120, (35, "05/11/2026"), (84, "PAGAMENTOS"), (475, "10,00"))],
        [_linha(27, (35, "05/11/2026"), (84, "RECEBIMENTOS"), (475, "20,00"))],
    ])
    assert [l.historico for l in lancamentos] == ["PAGAMENTOS", "RECEBIMENTOS"]
