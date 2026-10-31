"""CLI utilities for explicitly installing local machine-translation models."""

import json
from pathlib import Path

import click
from flask import current_app


def register_local_translation_cli(app):
    @app.cli.command("setup-local-translation")
    @click.option("--force", is_flag=True, help="Replace an existing converted model.")
    @click.option("--repair", is_flag=True, help="Repair an incomplete backup installation when needed.")
    def setup_local_translation(force=False, repair=False):
        """Download, convert, and cache the configured NLLB model."""
        from ctranslate2.converters import TransformersConverter
        from huggingface_hub import HfApi
        from transformers import AutoTokenizer

        from .models import Project, ProjectStatus
        from .providers.local_translation import LocalNllbTranslationProvider, MODEL_METADATA_FILENAME

        model_name = current_app.config["LOCAL_MT_MODEL"]
        revision = current_app.config["LOCAL_MT_MODEL_REVISION"]
        model_dir = Path(current_app.config["LOCAL_MT_MODEL_DIR"])
        tokenizer_dir = Path(current_app.config["LOCAL_MT_TOKENIZER_DIR"])
        cache_dir = Path(current_app.config["WHISPER_MODEL_DIR"]) / "huggingface"
        model_dir.parent.mkdir(parents=True, exist_ok=True)
        tokenizer_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        def write_metadata():
            metadata = {
                "schema_version": 1,
                "model": model_name,
                "revision": revision,
                "quantization": current_app.config["LOCAL_MT_COMPUTE_TYPE"],
            }
            (model_dir / MODEL_METADATA_FILENAME).write_text(
                json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
            )

        if Project.query.filter(Project.status.in_([ProjectStatus.PROCESSING, ProjectStatus.RENDERING])).first():
            raise click.ClickException("Wait for active processing to finish before installing the backup model.")
        def verify_model():
            click.echo("Checking a real CPU translation...")
            output = LocalNllbTranslationProvider().translate("Hello, how are you?", "en", "es")
            if not output.strip():
                raise RuntimeError("The backup model returned no translation.")

        if (model_dir / "model.bin").is_file() and not force:
            readiness = LocalNllbTranslationProvider().check_ready()
            if readiness.status == "pass":
                try:
                    verify_model()
                    click.echo(f"Local translation model is ready at {model_dir}")
                    return
                except Exception as exc:
                    if not repair:
                        raise click.ClickException(f"Backup model check failed: {exc}. Run setup-local-translation --repair.") from exc
            if not repair:
                raise click.ClickException("An incomplete or mismatched backup model exists. Run setup-local-translation --repair.")
            click.echo("Repairing the selected NLLB backup model...")
            force = True

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
        if not (model_dir / "model.bin").is_file():
            raise click.ClickException("Model conversion did not produce a usable NLLB model.")
        write_metadata()
        LocalNllbTranslationProvider._translator_cache.clear()
        LocalNllbTranslationProvider._tokenizer_cache.clear()
        try:
            verify_model()
        except Exception as exc:
            (model_dir / MODEL_METADATA_FILENAME).unlink(missing_ok=True)
            raise click.ClickException(f"The backup model did not pass its translation check: {exc}") from exc
        click.echo(f"Local translation model is ready at {model_dir}")
