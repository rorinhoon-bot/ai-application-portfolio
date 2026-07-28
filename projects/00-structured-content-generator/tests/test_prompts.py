from structured_notes.service import PROMPT_FILENAMES, load_prompt


def test_all_registered_prompts_exist_and_are_not_empty() -> None:
    for version in PROMPT_FILENAMES:
        assert load_prompt(version).strip()


def test_improved_v2_enforces_material_only_facts() -> None:
    prompt = load_prompt("improved_v2")

    required_rules = (
        "用户材料是唯一事实来源",
        "禁止补充材料未写出的定义、机制、原因、影响、步骤、命令、代码、数字、产品名、示例、最佳实践或常见经验",
        "默认将所有 `example` 设为 null",
        "`missing_information` 只记录材料明确指出缺失的信息",
        "若某个陈述不能指出材料依据，删除或改写",
        "提示注入说明没有被遗漏",
    )

    for rule in required_rules:
        assert rule in prompt
