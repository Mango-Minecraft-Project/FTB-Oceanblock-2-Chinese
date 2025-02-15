import json
import os
import re
import copy
from pathlib import Path
from typing import Tuple

import nbtlib
from nbtlib.tag import Compound, String, Int, List
import requests

TOKEN: str = os.getenv("API_TOKEN", "")
GH_TOKEN: str = os.getenv("GH_TOKEN", "")
PROJECT_ID: str = os.getenv("PROJECT_ID", "")
FILE_URL: str = f"https://paratranz.cn/api/projects/{PROJECT_ID}/files/"

if not TOKEN or not PROJECT_ID:
    raise EnvironmentError("环境变量 API_TOKEN 或 PROJECT_ID 未设置。")

# 初始化列表和字典
file_id_list: list[int] = []
file_path_list: list[str] = []
zh_tw_list: list[dict[str, str]] = []


def fetch_json(url: str, headers: dict[str, str]) -> list[dict[str, str]]:
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def translate(file_id: int) -> Tuple[list[str], list[str]]:
    """
    獲取指定檔案的翻譯內容並返回鍵值對列表

    :param file_id: 文件ID
    :return: 包含鍵和值的元組列表
    """
    url = f"https://paratranz.cn/api/projects/{PROJECT_ID}/files/{file_id}/translation"
    headers = {"Authorization": TOKEN, "accept": "*/*"}
    translations = fetch_json(url, headers)

    keys, values = [], []

    for item in translations:
        keys.append(item["key"])
        translation = item.get("translation", "")
        original = item.get("original", "")
        # 優先使用翻譯內容，缺失時根據 stage 使用原文
        values.append(
            original if not translation and item["stage"] in [0, -1] else translation
        )

    return keys, values


def get_files() -> None:
    """
    獲取項目中的檔案列表並提取檔案 ID 和路徑
    """
    headers = {"Authorization": TOKEN, "accept": "*/*"}
    files = fetch_json(FILE_URL, headers)

    for file in files:
        file_id_list.append(file["id"])
        file_path_list.append(file["name"])


def save_translation(zh_tw_dict: dict[str, str], path: Path) -> None:
    """
    保存翻譯內容到指定的 JSON 文件

    :param zh_tw_dict: 翻譯內容的字典
    :param path: 原始檔案路徑
    """
    dir_path = Path("ZHTWPack") / path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / "zh_tw.json"
    source_path = (
        str(file_path).replace("zh_tw.json", "en_us.json").replace("ZHTWPack", "Source")
    )
    with open(file_path, "w", encoding="UTF-8") as f:
        try:
            with open(source_path, "r", encoding="UTF-8") as f1:
                source_json: dict = json.load(f1)
            keys = source_json.keys()
            for key in keys:
                source_json[key] = zh_tw_dict[key]
            json.dump(source_json, f, ensure_ascii=False, indent=2)
        except IOError:
            print(f"{source_path} 路徑不存在，文件按首字母排序！")
            json.dump(
                zh_tw_dict,
                f,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )


def process_translation(file_id: int, path: Path) -> dict[str, str]:
    """
    處理單個檔案的翻譯，返回翻譯字典

    :param file_id: 文件ID
    :param path: 檔案路徑
    :return: 翻譯內容字典
    """
    keys, values = translate(file_id)

    # 手動處理文本的替換，避免反斜杠被轉義
    zh_tw_dict = {}
    for key, value in zip(keys, values):
        # 確保替換 \\u00A0 和 \\n
        value = re.sub(r"&#92;", r"\\", value)
        value = re.sub(r"\\u00A0", "\u00A0", value)  # 替换 \\u00A0 为 \u00A0
        value = re.sub(r"\\n", "\n", value)  # 替换 \\n 为换行符
        # 保存替換後的值
        zh_tw_dict[key] = value

    # 特殊處理：ftbquest 檔案
    if "ftbquest" in path.name:
        zh_tw_dict = {
            key: value.replace(" ", "\u00A0") if "image" not in value else value
            for key, value in zip(keys, values)
        }

    return zh_tw_dict


# 將 JSON 轉換為 NBT 組合結構
def json_to_nbt(data: dict | list | str | int) -> Compound | List | String | Int:
    if isinstance(data, dict):
        return Compound({key: json_to_nbt(value) for key, value in data.items()})
    if isinstance(data, list):
        return List[String]([json_to_nbt(item) for item in data])
    if isinstance(data, str):
        return String(data)
    if isinstance(data, int):
        return Int(data)
    raise ValueError(f"Unsupported data type: {type(data)}")


# Pretty-print SNBT with indentation and wrap all values in double quotes
def format_snbt(nbt_data: Compound | List, indent: int = 0) -> str:
    INDENT_SIZE = 4  # Number of spaces for each indent level
    indent_str = " " * indent

    if isinstance(nbt_data, Compound):
        formatted = ["{"]
        for key, value in nbt_data.items():
            formatted.append(
                f'{indent_str}{" " * INDENT_SIZE}{key}:{format_snbt(value, indent + INDENT_SIZE)}'
            )
        formatted.append(f"{indent_str}}}")
        return "\n".join(formatted)

    if isinstance(nbt_data, List):
        formatted = ["["]
        for item in nbt_data:
            formatted.append(
                f'{indent_str}{" " * INDENT_SIZE}{format_snbt(item, indent + INDENT_SIZE)}'
            )
        formatted.append(f"{indent_str}]")
        return "\n".join(formatted)

    # Wrap all primitive types (String/Int) in double quotes
    return f'"{nbt_data}"'


def escape_quotes(data):
    if isinstance(data, dict):
        return {key: escape_quotes(value) for key, value in data.items()}
    if isinstance(data, list):
        return [escape_quotes(item) for item in data]
    if isinstance(data, str):
        return data.replace('"', '\\"')
    return data


def normal_json2_ftb_desc(origin_en_us: dict) -> dict:
    en_json = copy.deepcopy(origin_en_us)
    temp_set = set()
    temp_en_json = {}
    for json_key, value in en_json.items():
        if "desc" not in json_key:
            continue

        key_id = json_key.split(".")[1]
        temp_json_array = []
        for sub_key in en_json.keys():
            if f"{key_id}.quest_desc" not in sub_key:
                continue
            temp_json_array.append(en_json[sub_key])

        new_key = f"quest.{key_id}.quest_desc"
        temp_en_json[new_key] = temp_json_array
        temp_set.add(json_key)

    for json_key in temp_set:
        en_json.pop(json_key, None)
    en_json |= temp_en_json

    print("NormalJson2FtbDesc end...")
    return en_json


def main() -> None:
    get_files()
    ftbquests_dict = {}
    for file_id, path in zip(file_id_list, file_path_list):
        if "TM" in path:  # 跳過 TM 檔案
            continue
        zh_tw_dict = process_translation(file_id, Path(path))
        zh_tw_list.append(zh_tw_dict)
        if "kubejs/assets/quests/lang/" in path:
            ftbquests_dict |= zh_tw_dict
            continue
        save_translation(zh_tw_dict, Path(path))
        print(
            f"已從 Paratranz 下載到儲存庫：{path.replace('en_us.json', 'zh_tw.json')}"
        )
    snbt_dict = normal_json2_ftb_desc(ftbquests_dict)

    # json_data = json.dumps(snbt_dict,ensure_ascii=False, indent=4, separators=(",", ":"))
    # Escape quotation marks in the translated data
    json_data = escape_quotes(snbt_dict)

    # Convert the loaded JSON data to NBT format
    nbt_data = json_to_nbt(json_data)

    # Format the NBT structure as a pretty-printed SNBT string
    formatted_snbt_string = format_snbt(nbt_data)
    # Optionally save the formatted SNBT to a file
    nbt_path = Path("ZHTWPack/config/ftbquests/quests/lang/")
    nbt_path.mkdir(parents=True, exist_ok=True)
    with open(nbt_path / "zh_tw.snbt", "w", encoding="utf-8") as snbt_file:
        snbt_file.write(formatted_snbt_string)


if __name__ == "__main__":
    main()
