"""Explicit, isolated model preparation for the local setup wizard."""

import click


def register_setup_cli(app):
    @app.cli.command("prepare-transcription")
    def prepare_transcription():
        from .providers import get_transcription_provider

        click.echo("Preparing the selected WhisperX transcription model. The first run downloads model files.")
        check = get_transcription_provider().check_ready(deep=False, load_models=True, diarize=False)
        click.echo(check.message)
        if not check.ready:
            raise click.exceptions.Exit(1)
        click.echo("Transcription model preparation completed. Alignment models can still download on first use for a language.")
