from cortes.config import CaptionConfig
from cortes.models import Word
from cortes.stages import subtitles


def words_from(pairs):
    return [Word(start=s, end=e, text=t) for s, e, t in pairs]


def test_chunk_respeita_maximo_de_palavras():
    config = CaptionConfig(max_words=3, max_chars=999, max_seconds=999)
    words = words_from([(i * 0.3, i * 0.3 + 0.3, f"p{i}") for i in range(9)])
    chunks = subtitles.chunk_words(words, config)
    assert [len(c.text.split()) for c in chunks] == [3, 3, 3]


def test_chunk_respeita_maximo_de_caracteres():
    config = CaptionConfig(max_words=99, max_chars=12, max_seconds=999)
    words = words_from([(i * 0.3, i * 0.3 + 0.3, "palavra") for i in range(4)])
    chunks = subtitles.chunk_words(words, config)
    assert all(len(c.text) <= 12 for c in chunks)


def test_chunk_quebra_em_pausa_longa():
    config = CaptionConfig(max_words=99, max_chars=999, max_seconds=999)
    words = words_from([(0.0, 0.4, "antes"), (3.0, 3.4, "depois")])
    chunks = subtitles.chunk_words(words, config)
    assert [c.text for c in chunks] == ["antes", "depois"]


def test_chunk_ignora_palavra_vazia():
    config = CaptionConfig()
    words = words_from([(0.0, 0.4, "ola"), (0.5, 0.6, "   "), (0.7, 1.0, "mundo")])
    chunks = subtitles.chunk_words(words, config)
    assert " ".join(c.text for c in chunks) == "ola mundo"


def test_ass_usa_tempo_relativo_ao_corte():
    config = CaptionConfig(uppercase=False)
    words = words_from([(65.0, 65.5, "ola"), (65.6, 66.2, "mundo")])
    ass = subtitles.build_ass(words, 60.0, 90.0, config, (1080, 1920))
    assert "Dialogue: 0,0:00:05.00" in ass
    assert "0:01:05" not in ass, "não pode vazar o tempo do vídeo original"


def test_ass_descarta_palavra_fora_do_corte():
    config = CaptionConfig(uppercase=False)
    words = words_from([(10.0, 10.5, "fora"), (65.0, 65.5, "dentro")])
    ass = subtitles.build_ass(words, 60.0, 90.0, config, (1080, 1920))
    assert "dentro" in ass and "fora" not in ass


def test_ass_tem_cabecalho_e_resolucao_do_video_final():
    ass = subtitles.build_ass(
        words_from([(1.0, 1.4, "oi")]), 0.0, 30.0, CaptionConfig(), (1080, 1920)
    )
    assert "[Script Info]" in ass and "[V4+ Styles]" in ass and "[Events]" in ass
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass


def test_ass_maiusculas_quando_configurado():
    ass = subtitles.build_ass(
        words_from([(1.0, 1.4, "oi")]), 0.0, 30.0, CaptionConfig(uppercase=True), (1080, 1920)
    )
    assert ",OI" in ass


def test_ass_escapa_chave_que_quebraria_o_formato():
    config = CaptionConfig(uppercase=False)
    ass = subtitles.build_ass(
        words_from([(1.0, 1.4, "{\\an8}texto")]), 0.0, 30.0, config, (1080, 1920)
    )
    assert "{\\an8}" not in ass, "chaves viram tag de override no ASS"
