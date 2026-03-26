# EAP Orçamentária

Aplicação em Streamlit para enviar projetos em PDF e gerar uma EAP estruturada para orçamento, com lista de materiais e exportação em Excel estilizado.

## Funcionalidades

- Upload de PDF
- Extração de texto por página
- OCR opcional para páginas escaneadas
- Geração de EAP em português com numeração automática
- Lista de materiais em português revisada por IA
- Download em Excel com cores e hierarquia
- Download em JSON

## Estrutura da planilha

O arquivo final de Excel inclui colunas prontas para orçamento:

- ITEM
- DESCRIÇÃO
- UNIDADE
- QUANTIDADE
- PREÇO UNITÁRIO
- PREÇO TOTAL

Os itens são numerados automaticamente como `1`, `1.1`, `1.2`, `2` e assim por diante.

## Como rodar localmente

1. Instale as dependências:

```bash
pip install -r requirements.txt
```

2. Configure a chave da IA:

```bash
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```

Também é possível usar um arquivo local não commitado em `.streamlit/secrets.toml`.

3. Execute o app:

```bash
streamlit run app.py
```

## Deploy no Streamlit Cloud

1. Publique este repositório no GitHub.
2. Crie um app no Streamlit Cloud apontando para este repositório.
3. Use `app.py` como arquivo principal.
4. Adicione os secrets no painel do Streamlit Cloud:

```toml
OPENAI_API_KEY = "sua_chave_aqui"
OPENAI_MODEL = "gpt-4o-mini"
```

## Observações

- A aplicação está em português.
- A saída depende da IA para análise, validação e filtragem.
- A chave OpenAI é obrigatória para gerar o resultado.
- Os valores de `PREÇO UNITÁRIO` e `PREÇO TOTAL` são gerados como `0,00` até você integrar sua base de custos.
