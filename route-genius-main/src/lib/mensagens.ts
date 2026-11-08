/** Textos prontos para copiar (WhatsApp / Teams / e-mail). */

export interface LinhaMensagem {
  cliente: string;
  numero_pedido: string;
  of_ano?: string;
  peso_kg: number;
  data_producao?: string;
  representante?: string;
}

export const kg = (n: number) => `${(n || 0).toLocaleString("pt-BR")} kg`;

export function dataBR(texto?: string): string {
  if (!texto) return "";
  const iso = texto.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return iso ? `${iso[3]}/${iso[2]}/${iso[1]}` : texto;
}

function linhaTexto(c: LinhaMensagem, comRep = false): string {
  const of = c.of_ano ? ` OF ${c.of_ano}` : "";
  const prod = c.data_producao ? ` — Dt. Produção ${c.data_producao}` : "";
  const rep = comRep && c.representante ? ` — Rep. ${c.representante}` : "";
  return `• ${c.cliente} — Pedido ${c.numero_pedido}${of} — ${kg(c.peso_kg)}${prod}${rep}`;
}

function primeiroNome(rep: string): string {
  const n = rep.split(" ")[0] ?? rep;
  return n.charAt(0) + n.slice(1).toLowerCase();
}

/** Para o representante: "podemos carregar hoje?" */
export function mensagemRepresentante(rep: string, linhas: LinhaMensagem[], dataRef = ""): string {
  const total = linhas.reduce((s, c) => s + (c.peso_kg || 0), 0);
  const hoje = dataRef ? ` hoje (${dataBR(dataRef)})` : " hoje";
  return (
    `Olá ${primeiroNome(rep)}, tudo bem?\n\n` +
    `Os materiais abaixo já estão prontos na expedição, mas a data de produção ainda não chegou. ` +
    `Podemos carregar${hoje}?\n\n${linhas.map((l) => linhaTexto(l)).join("\n")}\n\nTotal: ${kg(total)}\n\nObrigado!`
  );
}

/** Para o comercial: pedidos com pagamento antecipado prontos para sair. */
export function mensagemComercial(linhas: LinhaMensagem[]): string {
  return (
    `Olá, tudo bem?\n\n` +
    `Os pedidos abaixo são de pagamento antecipado e o material está pronto. ` +
    `Podem confirmar o pagamento e liberar o faturamento por e-mail?\n\n` +
    `${linhas.map((l) => linhaTexto(l, true)).join("\n")}\n\nObrigado!`
  );
}

export async function copiarTexto(texto: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(texto);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = texto;
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  }
}
