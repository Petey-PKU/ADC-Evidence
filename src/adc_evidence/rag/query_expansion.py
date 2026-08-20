from __future__ import annotations


TERM_EXPANSIONS = {
    "靶点": "target antigen",
    "载荷": "payload warhead cytotoxic",
    "连接子": "linker cleavable non-cleavable",
    "药物抗体比": "drug antibody ratio DAR",
    "适应证": "indication condition cancer tumor",
    "临床试验": "clinical trial study",
    "招募": "recruiting recruitment",
    "入组": "enrollment participants",
    "主要终点": "primary outcome endpoint",
    "疗效": "efficacy response survival",
    "安全性": "safety adverse event toxicity",
    "毒性": "toxicity adverse event safety",
    "乳腺癌": "breast cancer",
    "胃癌": "gastric cancer",
    "肺癌": "lung cancer NSCLC",
    "卵巢癌": "ovarian cancer",
    "尿路上皮癌": "urothelial cancer",
    "三阴性": "triple-negative TNBC",
    "状态": "status",
    "阶段": "phase",
    "研究": "study trial",
    "文献": "article publication PubMed",
    "机制": "mechanism activity internalization",
}


def expand_query(query: str) -> str:
    additions = [english for chinese, english in TERM_EXPANSIONS.items() if chinese in query]
    return " ".join([query, *additions]).strip()
