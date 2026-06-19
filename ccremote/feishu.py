"""Feishu/Lark messaging: build a client and send text/images/reactions.

All functions take an explicit `client` (built by build_client) so they are
stateless and testable. Every call is best-effort: failures are logged and
signalled by return value, never raised, so a messaging hiccup can't crash the
bridge loop or block a Stop hook.
"""

import json
import logging

log = logging.getLogger("ccremote.feishu")


def build_client(app_id, app_secret):
    """Create a Lark client. Imports lark_oapi lazily so importing this module
    is cheap and the failure (missing dep) is localized here."""
    import lark_oapi as lark

    return lark.Client.builder().app_id(app_id).app_secret(app_secret).build()


def send_text(client, chat_id, text, receive_id_type="chat_id"):
    """Send a plain-text message to a chat. Returns True on confirmed send.
    receive_id_type lets callers target open_id etc.; defaults to chat_id so
    existing positional callers are unchanged."""
    if not client or not chat_id:
        return False
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    try:
        resp = client.im.v1.message.create(
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            .build()
        )
        return bool(resp.success())
    except Exception as e:
        log.error(f"send_text failed: {e}")
        return False


def send_image(client, chat_id, image_path):
    """Upload an image file and send it to a chat. Returns True on confirmed send."""
    if not client or not chat_id:
        return False
    from lark_oapi.api.im.v1 import (
        CreateImageRequest,
        CreateImageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    try:
        with open(image_path, "rb") as f:
            up = client.im.v1.image.create(
                CreateImageRequest.builder()
                .request_body(
                    CreateImageRequestBody.builder().image_type("message").image(f).build()
                )
                .build()
            )
        if not (up.success() and up.data and up.data.image_key):
            log.error(f"image upload failed: code={getattr(up, 'code', '?')}")
            return False
        resp = client.im.v1.message.create(
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("image")
                .content(json.dumps({"image_key": up.data.image_key}))
                .build()
            )
            .build()
        )
        return bool(resp.success())
    except Exception as e:
        log.error(f"send_image failed: {e}")
        return False


def add_reaction(client, message_id, emoji_type):
    """Add an emoji reaction. Returns reaction_id or None."""
    if not client or not message_id:
        return None
    from lark_oapi.api.im.v1 import (
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        Emoji,
    )

    try:
        resp = client.im.v1.message_reaction.create(
            CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                CreateMessageReactionRequestBody.builder()
                .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                .build()
            )
            .build()
        )
        if resp.success() and resp.data:
            return resp.data.reaction_id
        log.error(f"add_reaction {emoji_type} failed: code={getattr(resp, 'code', '?')}")
        return None
    except Exception as e:
        log.error(f"add_reaction error: {e}")
        return None


def del_reaction(client, message_id, reaction_id):
    """Best-effort remove a reaction."""
    if not client or not message_id or not reaction_id:
        return
    from lark_oapi.api.im.v1 import DeleteMessageReactionRequest

    try:
        client.im.v1.message_reaction.delete(
            DeleteMessageReactionRequest.builder()
            .message_id(message_id)
            .reaction_id(reaction_id)
            .build()
        )
    except Exception as e:
        log.error(f"del_reaction error: {e}")


def download_image(client, message_id, image_key, dest_path):
    """Download a message image resource to dest_path. Returns dest_path or None.
    Requires the im:resource permission."""
    if not client or not message_id or not image_key:
        return None
    from lark_oapi.api.im.v1 import GetMessageResourceRequest

    try:
        resp = client.im.v1.message_resource.get(
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(image_key)
            .type("image")
            .build()
        )
        if not resp.success() or resp.file is None:
            log.error(f"image download failed: code={getattr(resp, 'code', '?')}")
            return None
        with open(dest_path, "wb") as f:
            f.write(resp.file.read())
        log.info(f"Image saved: {dest_path}")
        return dest_path
    except Exception as e:
        log.error(f"download_image error: {e}")
        return None


def update_chat_name(client, chat_id, name):
    """Rename a group chat. Returns (ok, err): (True, None) on success,
    (False, reason) otherwise. Never raises — best-effort like the rest of this
    module, so a rename hiccup can't fail a /bind. Requires the im:chat scope."""
    if not client or not chat_id:
        return (False, "no client/chat_id")
    try:
        from lark_oapi.api.im.v1 import UpdateChatRequest, UpdateChatRequestBody

        resp = client.im.v1.chat.update(
            UpdateChatRequest.builder()
            .chat_id(chat_id)
            .request_body(UpdateChatRequestBody.builder().name(name).build())
            .build()
        )
        if resp.success():
            return (True, None)
        log.error(f"update_chat_name failed: code={getattr(resp, 'code', '?')}")
        return (False, f"code={getattr(resp, 'code', '?')}")
    except Exception as e:
        log.error(f"update_chat_name error: {e}")
        return (False, str(e))


def build_markdown_card(md_text, header_title=None, header_template=None,
                        footer=None):
    """Build a Feishu card JSON v2 (schema 2.0) carrying one markdown element.
    v2 is required for headings/inline-code/table/quote to render (the legacy
    no-schema card's tag:markdown does not support them — verified 2026-06-19).
    A header is added only when header_title is given. A non-empty `footer`
    string is appended as a small grey note at the bottom: a divider (hr) then a
    grey markdown line. v2 body elements only accept known tags — `plain_text`
    is NOT one (Feishu rejects it, code 200621) — so the grey text rides on a
    markdown <font> element rather than a plain_text element."""
    elements = [{"tag": "markdown", "content": md_text}]
    if footer:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "markdown",
            "content": f"<font color='grey'>{footer}</font>",
        })
    card = {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "body": {"elements": elements},
    }
    if header_title:
        header = {"title": {"tag": "plain_text", "content": header_title}}
        if header_template:
            header["template"] = header_template
        card["header"] = header
    return card


def send_card(client, receive_id, card, receive_id_type="chat_id"):
    """Send an interactive card (msg_type=interactive). `card` is a card dict
    (see build_markdown_card). Best-effort like send_text: never raises,
    returns True only on confirmed send. Uses the same im.v1.message.create as
    send_text, so the existing im:message:send_as_bot scope covers it
    (empirically confirmed 2026-06-19)."""
    if not client or not receive_id:
        return False
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    try:
        resp = client.im.v1.message.create(
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("interactive")
                .content(json.dumps(card))
                .build()
            )
            .build()
        )
        return bool(resp.success())
    except Exception as e:
        log.error(f"send_card failed: {e}")
        return False


def send_markdown(client, receive_id, md_text, text_fallback,
                  receive_id_type="chat_id", header_title=None,
                  header_template=None, footer=None):
    """Send md_text as a v2 markdown card; if the card API fails, fall back to
    sending text_fallback as plain text. The card-failure-never-loses-the-message
    contract lives here. md_text and text_fallback are already truncated to
    their channel's limit by the caller (cards and plain text have different
    ceilings). `footer`, if given, is a small grey note at the card bottom; it
    rides only on the card — the plain-text fallback stays clean. Returns True
    if either send confirmed."""
    if not client or not receive_id:
        return False
    card = build_markdown_card(md_text, header_title, header_template, footer)
    if send_card(client, receive_id, card, receive_id_type):
        return True
    return send_text(client, receive_id, text_fallback, receive_id_type)
