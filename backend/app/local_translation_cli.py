"""CLI utilities for explicitly installing local machine-translation models."""

import json
from pathlib import Path

import click
from flask import current_app


def register_local_translation_cli(app):
    @app.cli.command("setup-local-translation")
    @click.option("--force", is_flag=True, help="Replace an existing converted model.")
    def setup_local_translation(force=False):
        """Download, convert, and cache the configured NLLB model."""
        from ctranslate2.converters import TransformersConverter
        from huggingface_hub import HfApi
        from transformers import AutoTokenizer

        model_name = current_app.config["LOCAL_MT_MODEL"]
        revision = current_app.config["LOCAL_MT_MODEL_REVISION"]
        model_dir = Path(current_app.config["LOCAL_MT_MODEL_DIR"])
        tokenizer_dir = Path(current_app.config["LOCAL_MT_TOKENIZER_DIR"])
        cache_dir = Path(current_app.config["WHISPER_MODEL_DIR"]) / "huggingface"
        model_dir.parent.mkdir(parents=True, exist_ok=True)
        tokenizer_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        def write_metadata():
            from .providers.local_translation import MODEL_METADATA_FILENAME
            metadata = {
                "schema_version": 1,
                "model": model_name,
                "revision": revision,
                "quantization": current_app.config["LOCAL_MT_COMPUTE_TYPE"],
            }
            (model_dir / MODEL_METADATA_FILENAME).write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )

        if (model_dir / "model.bin").is_file() and not force:
            write_metadata()
            click.echo(f"Local translation model already exists at {model_dir}")
            return

        if current_app.config.get("LOCAL_MT_REQUIRE_SAFETENSORS", True):
            info = HfApi().model_info(model_name, revision=revision)
            files = {item.rfilename for item in (info.siblings or [])}
            if "model.safetensors" not in files:
                raise click.ClickException(
                    "Configured NLLB revision does not contain model.safetensors."
                )

        click.echo(f"Downloading tokenizer for {model_name}@{revision}...")
        tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            revision=revision,
            cache_dir=str(cache_dir),
            trust_remote_code=False,
        )
        tokenizer.save_pretrained(tokenizer_dir)

        click.echo("Converting NLLB to CTranslate2 INT8. This can take several minutes...")
        class CompatibleNllbConverter(TransformersConverter):
            """Bridge Transformers' scaled embedding object to CT2 4.4."""

            @staticmethod
            def load_model(model_class, model_name_or_path, **kwargs):
                model = model_class.from_pretrained(model_name_or_path, **kwargs)
                for module in (model.model.encoder, model.model.decoder):
                    if not hasattr(module, "embed_scale"):
                        module.embed_scale = module.embed_tokens.embed_scale
                return model

        converter = CompatibleNllbConverter(
            model_name,
            revision=revision,
            low_cpu_mem_usage=True,
            trust_remote_code=False,
        )
        converter.convert(
            str(model_dir),
            quantization=current_app.config["LOCAL_MT_COMPUTE_TYPE"],
            force=force or model_dir.exists(),
        )
        write_metadata()
        click.echo(f"Local translation model is ready at {model_dir}")
