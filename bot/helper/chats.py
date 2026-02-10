from asyncio import gather, create_task
from bot.helper.database import Database
from bot.telegram import StreamBot
from bot.config import Telegram
import base64

db = Database()

# ── Default fallback thumbnail SVGs (base64-encoded) ──────────────────────────

_FOLDER_SVG = base64.b64encode(b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
<rect width="120" height="120" fill="#0f1923"/>
<rect x="25" y="42" width="70" height="46" rx="5" fill="#FFB74D" opacity="0.9"/>
<rect x="25" y="35" width="30" height="12" rx="4" fill="#FFA726"/>
<rect x="30" y="52" width="60" height="3" rx="1" fill="#fff" opacity="0.2"/>
<rect x="30" y="60" width="45" height="3" rx="1" fill="#fff" opacity="0.15"/>
</svg>''').decode()
FOLDER_FALLBACK = f"data:image/svg+xml;base64,{_FOLDER_SVG}"

_VIDEO_SVG = base64.b64encode(b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">
<rect width="320" height="180" fill="#0f1923"/>
<circle cx="160" cy="90" r="36" fill="#42A5F5" opacity="0.15"/>
<circle cx="160" cy="90" r="28" fill="#42A5F5" opacity="0.25"/>
<polygon points="150,70 150,110 185,90" fill="#42A5F5"/>
</svg>''').decode()
VIDEO_FALLBACK = f"data:image/svg+xml;base64,{_VIDEO_SVG}"

_PDF_SVG = base64.b64encode(b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">
<rect width="320" height="180" fill="#0f1923"/>
<rect x="120" y="25" width="55" height="70" rx="4" fill="#EF5350"/>
<path d="M155,25 L175,25 L175,45 L155,25 Z" fill="#0f1923" opacity="0.3"/>
<rect x="130" y="50" width="35" height="3" rx="1" fill="#fff" opacity="0.4"/>
<rect x="130" y="58" width="28" height="3" rx="1" fill="#fff" opacity="0.3"/>
<rect x="130" y="66" width="32" height="3" rx="1" fill="#fff" opacity="0.3"/>
<text x="160" y="125" text-anchor="middle" fill="#EF5350" font-size="20" font-weight="bold" font-family="Arial,sans-serif">PDF</text>
</svg>''').decode()
PDF_FALLBACK = f"data:image/svg+xml;base64,{_PDF_SVG}"

_FILE_SVG = base64.b64encode(b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">
<rect width="320" height="180" fill="#0f1923"/>
<rect x="125" y="25" width="50" height="65" rx="4" fill="#78909C"/>
<path d="M155,25 L175,25 L175,45 L155,25 Z" fill="#0f1923" opacity="0.3"/>
<rect x="133" y="48" width="32" height="3" rx="1" fill="#fff" opacity="0.4"/>
<rect x="133" y="56" width="25" height="3" rx="1" fill="#fff" opacity="0.3"/>
<rect x="133" y="64" width="28" height="3" rx="1" fill="#fff" opacity="0.3"/>
<text x="160" y="120" text-anchor="middle" fill="#78909C" font-size="18" font-weight="bold" font-family="Arial,sans-serif">FILE</text>
</svg>''').decode()
FILE_FALLBACK = f"data:image/svg+xml;base64,{_FILE_SVG}"

_CHANNEL_SVG = base64.b64encode(b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
<rect width="120" height="120" fill="#0f1923"/>
<circle cx="60" cy="48" r="22" fill="#7E57C2" opacity="0.8"/>
<ellipse cx="60" cy="90" rx="30" ry="16" fill="#7E57C2" opacity="0.5"/>
</svg>''').decode()
CHANNEL_FALLBACK = f"data:image/svg+xml;base64,{_CHANNEL_SVG}"


def _get_file_fallback(file_type):
    """Return the appropriate fallback thumbnail based on file type."""
    ft = (file_type or '').lower()
    if 'video' in ft:
        return VIDEO_FALLBACK
    elif 'pdf' in ft:
        return PDF_FALLBACK
    else:
        return FILE_FALLBACK


async def get_chats():
    AUTH_CHANNEL = await db.get_variable('auth_channel')
    if AUTH_CHANNEL is None or AUTH_CHANNEL.strip() == '':
        AUTH_CHANNEL = Telegram.AUTH_CHANNEL
    else:
        AUTH_CHANNEL = [channel.strip() for channel in AUTH_CHANNEL.split(",")]
    
    return [{"chat-id": chat.id, "title": chat.title or chat.first_name, "type": chat.type.name} for chat in await gather(*[create_task(StreamBot.get_chat(int(channel_id))) for channel_id in AUTH_CHANNEL])]


async def posts_chat(channels):
    phtml = """
            <div class="col channel-card">
                <a href="/channel/{cid}">
                    <div class="card profile-card mb-2">
                    
                        <div class="img-container text-center"
                            style="width: 100px; height: 100px; display: inline-block; overflow: hidden; position: relative; border-radius: 50%; margin: 14px auto 0;">
                            <img src="https://cdn.jsdelivr.net/gh/weebzone/weebzone/data/Surf-TG/src/loading.gif" class="card-img-top lzy_img"
                                data-src="{img}" alt="{title}"
                                onerror="this.onerror=null;this.src='{fallback}'"
                                style="object-fit: cover; width: 100%; height: 100%; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);">
                        </div>
            
                        <div class="card-body p-1 text-center">
                            <div>
                                <h6 class="card-title">{title}</h6>
                                <span class="badge bg-warning">{ctype}</span>
                            </div>
                        </div>
                    </div>
                </a>
            </div>
"""
    return ''.join(phtml.format(cid=str(channel["chat-id"]).replace("-100", ""), img=f"/api/thumb/{channel['chat-id']}", title=channel["title"], ctype=channel['type'], fallback=CHANNEL_FALLBACK) for channel in channels)


async def post_playlist(playlists):
    dhtml = """
    <div class="col">

        <div class="card profile-card mb-2" style="cursor: pointer;">
            <a href="" onclick="openEditPopupForm(event, '{img}', '{ctype}', '{cid}', '{title}')"
                class="admin-only position-absolute top-0 end-0 m-2" data-bs-toggle="modal" data-bs-target="#editFolderModal"
                style="z-index: 2;"><i class="bi bi-pencil-square" style="color: rgba(255,255,255,0.5);"></i>
            </a>
            <a href="/playlist?db={cid}" style="text-decoration: none; color: inherit; display: block;">
                <div class="img-container text-center"
                    style="width: 100px; height: 100px; display: inline-block; overflow: hidden; position: relative; border-radius: 50%; margin: 14px auto 0;">
                    <img src="https://cdn.jsdelivr.net/gh/weebzone/weebzone/data/Surf-TG/src/loading.gif"
                        class="card-img-top lzy_img" data-src="{img}" alt="{title}"
                        onerror="this.onerror=null;this.src='{fallback}'"
                        style="object-fit: cover; width: 100%; height: 100%; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);">
                </div>
                <div class="card-body p-1 text-center">
                    <div>
                        <h6 class="card-title">{title}</h6>
                        <span class="badge bg-warning">Folder</span>
                    </div>
                </div>
            </a>
        </div>

    </div>
    """

    return ''.join(dhtml.format(cid=playlist["_id"], img=playlist["thumbnail"] or FOLDER_FALLBACK, title=playlist["name"], ctype=playlist['parent_folder'], fallback=FOLDER_FALLBACK) for playlist in playlists)


async def posts_db_file(posts):
    phtml = """
    <div class="col">

        <div class="card mb-2" style="cursor: pointer;">
            <a href=""
                onclick="openPostEditPopupForm(event, '{img}', '{type}', '{size}', '{title}', '{cid}', '{ctype}')"
                class="admin-only position-absolute top-0 end-0 m-2" data-bs-toggle="modal" data-bs-target="#editModal"
                style="z-index: 2;"><i
                    class="bi bi-pencil-square" style="color: rgba(255,255,255,0.5);"></i></a>
            <a href="/watch/{chat_id}?id={id}&hash={hash}" style="text-decoration: none; color: inherit; display: block;">
                <img src="https://cdn.jsdelivr.net/gh/weebzone/weebzone/data/Surf-TG/src/loading.gif" data-src="{img}"
                    class="card-img-top lzy_img" alt="{title}"
                    onerror="this.onerror=null;this.src='{fallback}'">
                <div class="card-body">
                    <h6 class="card-title">{title}</h6>
                    <span class="badge bg-warning">{type}</span>
                    <span class="badge bg-info">{size}</span>
                </div>
            </a>
        </div>

    </div>
"""
    result = []
    for post in posts:
        fallback = _get_file_fallback(post.get('file_type', ''))
        thumb = post["thumbnail"] or fallback
        result.append(phtml.format(
            cid=post["_id"],
            chat_id=str(post["chat_id"]).replace("-100", ""),
            id=post["file_id"],
            img=thumb,
            title=post["name"],
            hash=post["hash"],
            size=post['size'],
            type=post['file_type'],
            ctype=post["parent_folder"],
            fallback=fallback
        ))
    return ''.join(result)
