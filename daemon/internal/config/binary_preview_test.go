package config

import (
	"strings"
	"testing"
)

// filesystem.binary_preview (ADR 0029 §4, §9; plan/31/03 §5).

func TestBinaryPreviewDefaultsWhenAbsent(t *testing.T) {
	cfg, err := Load(writeFile(t, "config.yaml", validConfig, 0o600))
	if err != nil {
		t.Fatal(err)
	}
	bp := cfg.Filesystem.BinaryPreview
	if !bp.PreviewEnabled() || !cfg.BinaryPreviewFromDefault {
		t.Fatal("absent switch means enabled, and the startup log must know it was inherited (OD-5)")
	}
	if bp.ImageMaxBytes != 8*1024*1024 || bp.ImageMaxPixels != 16777216 ||
		bp.ImageMaxSide != 8192 || bp.PDFMaxBytes != 16*1024*1024 {
		t.Fatalf("defaults: %+v", bp)
	}
}

func TestBinaryPreviewExplicitSwitchIsNotFromDefault(t *testing.T) {
	for _, value := range []string{"true", "false"} {
		body := validConfig + "filesystem:\n  binary_preview:\n    enabled: " + value + "\n"
		cfg, err := Load(writeFile(t, "config.yaml", body, 0o600))
		if err != nil {
			t.Fatal(err)
		}
		if cfg.BinaryPreviewFromDefault {
			t.Fatalf("enabled: %s was written by an operator", value)
		}
		if cfg.Filesystem.BinaryPreview.PreviewEnabled() != (value == "true") {
			t.Fatalf("enabled: %s not honoured", value)
		}
	}
}

func TestBinaryPreviewLimitsCanOnlyBeLowered(t *testing.T) {
	lowered := validConfig + "filesystem:\n  binary_preview:\n    image_max_bytes: 1048576\n    image_max_pixels: 1000000\n    image_max_side: 2048\n    pdf_max_bytes: 4194304\n"
	cfg, err := Load(writeFile(t, "config.yaml", lowered, 0o600))
	if err != nil {
		t.Fatalf("lowering must be allowed: %v", err)
	}
	if bp := cfg.Filesystem.BinaryPreview; bp.ImageMaxSide != 2048 || bp.PDFMaxBytes != 4194304 {
		t.Fatalf("lowered limits not applied: %+v", bp)
	}
	for key, value := range map[string]string{
		"image_max_bytes": "8388609", "image_max_pixels": "16777217",
		"image_max_side": "8193", "pdf_max_bytes": "16777217", "pdf_max_bytes ": "-1",
	} {
		body := validConfig + "filesystem:\n  binary_preview:\n    " + strings.TrimSpace(key) + ": " + value + "\n"
		if _, err := Load(writeFile(t, "config.yaml", body, 0o600)); err == nil {
			t.Errorf("%s: %s must be refused at load (limits can only be lowered)", key, value)
		}
	}
}

func TestBinaryPreviewHasNoTypeKey(t *testing.T) {
	body := validConfig + "filesystem:\n  binary_preview:\n    allowed_types: [image/svg+xml]\n"
	if _, err := Load(writeFile(t, "config.yaml", body, 0o600)); err == nil {
		t.Fatal("the allowlist is the wire contract; a config key must not be able to widen it")
	}
}
