"""Standalone LightOnOCR CPU worker; communicates only through its job directory."""

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast


def _write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def run(directory: Path):
    import pypdfium2 as pdfium
    import torch
    from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor

    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    dtype = torch.bfloat16
    model = LightOnOcrForConditionalGeneration.from_pretrained(
        config["model"],
        dtype=dtype,
        attn_implementation="sdpa",
    )
    model.eval()
    # Transformers' generic generation annotations do not describe multimodal inputs.
    generate = cast(Callable[..., torch.Tensor], model.generate)
    processor = LightOnOcrProcessor.from_pretrained(config["model"], backend="pil")
    pages = []
    with pdfium.PdfDocument(str(directory / "input.pdf")) as pdf:
        for index in range(len(pdf)):
            _write(directory / "status.json", {"page": index + 1, "total": len(pdf)})
            page = pdf[index]
            scale = min(config["dpi"] / 72, 1540 / max(page.get_size()))
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil().convert("RGB")
            bitmap.close()
            page.close()
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": [{"type": "image", "image": image}]}
            ]
            inputs = cast(
                dict[str, torch.Tensor],
                processor.apply_chat_template(
                    messages,
                    add_generation_prompt=True,
                    tokenize=True,
                    return_dict=True,
                    return_tensors="pt",
                ),
            )
            inputs = {
                key: value.to(dtype=dtype) if value.is_floating_point() else value
                for key, value in inputs.items()
            }
            with torch.inference_mode():
                output = generate(
                    **inputs,
                    max_new_tokens=config["max_tokens"],
                    do_sample=False,
                    return_dict_in_generate=False,
                )
            generated = output[0, inputs["input_ids"].shape[1] :]
            eos = model.generation_config.eos_token_id
            eos_ids = eos if isinstance(eos, list) else [eos]
            if len(generated) >= config["max_tokens"] and int(generated[-1]) not in eos_ids:
                _write(directory / "result.json", {"error": "truncated"})
                return
            pages.append([index, processor.decode(generated, skip_special_tokens=True)])
            image.close()
        _write(directory / "result.json", {"pages": pages, "page_count": len(pdf)})


if __name__ == "__main__":
    job_directory = Path(sys.argv[1])
    try:
        run(job_directory)
    except Exception:  # noqa: BLE001 - report any worker failure to its parent, never publish partial OCR
        import traceback

        traceback.print_exc()
        _write(job_directory / "result.json", {"error": "model"})
        sys.exit(1)
