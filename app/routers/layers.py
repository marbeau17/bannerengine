"""Freeform layer management — spawn/edit/delete custom layers on the canvas."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(prefix="/api/layers", tags=["layers"])
templates = Jinja2Templates(directory="app/templates")

# Default geometry and style for each layer type
_LAYER_DEFAULTS: dict[str, dict] = {
    "rect":   {"fill": "#4f46e5", "label": "Rectangle"},
    "circle": {"fill": "#059669", "label": "Circle"},
    "text":   {"text": "Text Layer", "color": "#111111", "font_size": "24"},
    "image":  {"source_url": "", "label": "Image Layer"},
}


def _get_custom_layers(request: Request, pattern_id: str) -> list:
    return list(request.session.get(f"slots_{pattern_id}", {}).get("_custom_layers", []))


def _save_custom_layers(request: Request, pattern_id: str, layers: list) -> None:
    slots = dict(request.session.get(f"slots_{pattern_id}", {}))
    slots["_custom_layers"] = layers
    request.session[f"slots_{pattern_id}"] = slots


def _render_canvas(request: Request, pattern_id: str) -> HTMLResponse:
    """Re-render the preview canvas + sidebar OOB with current slot + custom layer state."""
    from app.routers.pages import _build_sidebar_layers

    template_service = request.app.state.template_service
    svg_renderer = request.app.state.svg_renderer
    template = template_service.get_template(pattern_id)
    slot_values = dict(request.session.get(f"slots_{pattern_id}", {}))
    svg_markup = svg_renderer.render(template, slot_values)

    canvas_html = templates.env.get_template("partials/preview_canvas.html").render(
        request=request,
        template=template,
        pattern_id=pattern_id,
        svg_markup=svg_markup,
    )
    sidebar_layers, _ = _build_sidebar_layers(template, slot_values)
    sidebar_html = templates.env.get_template("partials/layer_sidebar.html").render(
        request=request,
        sidebar_layers=sidebar_layers,
        pattern_id=pattern_id,
    )
    return HTMLResponse(content=canvas_html + sidebar_html)


@router.post("/{pattern_id}", response_class=HTMLResponse)
async def add_layer(request: Request, pattern_id: str):
    """Spawn a new freeform layer and return a refreshed preview canvas."""
    form = await request.form()
    layer_type = str(form.get("layer_type", "rect"))
    if layer_type not in _LAYER_DEFAULTS:
        layer_type = "rect"

    layer_id = f"custom_{uuid.uuid4().hex[:8]}"
    new_layer: dict = {
        "id": layer_id,
        "type": layer_type,
        "x": 10.0,
        "y": 10.0,
        "width": 30.0,
        "height": 20.0,
        "opacity": 1.0,
        **_LAYER_DEFAULTS[layer_type],
    }

    layers = _get_custom_layers(request, pattern_id)
    layers.append(new_layer)
    _save_custom_layers(request, pattern_id, layers)

    # Auto-stack: inject the new layer at the END of _order so it sorts to the
    # top of the Photoshop-style sidebar (reversed display = last item shown first).
    slots = dict(request.session.get(f"slots_{pattern_id}", {}))
    order: list = list(slots.get("_order", []))
    if layer_id not in order:
        order.append(layer_id)
    slots["_order"] = order
    request.session[f"slots_{pattern_id}"] = slots

    return _render_canvas(request, pattern_id)


@router.delete("/{pattern_id}/{layer_id}", response_class=HTMLResponse)
async def delete_layer(request: Request, pattern_id: str, layer_id: str):
    """Remove a freeform layer and return a refreshed preview canvas."""
    layers = [l for l in _get_custom_layers(request, pattern_id) if l["id"] != layer_id]
    _save_custom_layers(request, pattern_id, layers)
    return _render_canvas(request, pattern_id)


@router.patch("/{pattern_id}/{layer_id}", response_class=HTMLResponse)
async def update_layer(request: Request, pattern_id: str, layer_id: str):
    """Edit a freeform layer's properties and return a refreshed preview canvas."""
    form = await request.form()
    layers = _get_custom_layers(request, pattern_id)
    _NUMERIC_FIELDS = {"x", "y", "width", "height", "opacity"}
    for layer in layers:
        if layer["id"] == layer_id:
            for field in ("fill", "color", "opacity", "text", "font_size", "source_url", "x", "y", "width", "height"):
                val = form.get(field)
                if val is not None:
                    layer[field] = float(val) if field in _NUMERIC_FIELDS else str(val)
            break
    _save_custom_layers(request, pattern_id, layers)
    return _render_canvas(request, pattern_id)
