package config

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"gopkg.in/yaml.v3"
	"os"
)

type Credentials struct {
	NodeID     uuid.UUID `yaml:"node_id"`
	PrivateKey string    `yaml:"private_key"`
}

func GenerateKeypair() (publicKey string, privateKey string, err error) {
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return "", "", fmt.Errorf("generate node key: %w", err)
	}
	return base64.StdEncoding.EncodeToString(pub), base64.StdEncoding.EncodeToString(priv), nil
}

func (c *Credentials) SigningKey() (ed25519.PrivateKey, error) {
	raw, err := base64.StdEncoding.DecodeString(c.PrivateKey)
	if err != nil || len(raw) != ed25519.PrivateKeySize {
		return nil, errors.New("credentials contain an invalid private_key")
	}
	return ed25519.PrivateKey(raw), nil
}

func LoadCredentials(path string) (*Credentials, error) {
	data, err := readSecureFile(path)
	if err != nil {
		return nil, err
	}
	var creds Credentials
	if err := yaml.Unmarshal(data, &creds); err != nil {
		return nil, fmt.Errorf("parse credentials: %w", err)
	}
	if creds.NodeID == uuid.Nil || creds.PrivateKey == "" {
		return nil, errors.New("credentials must include node_id and private_key; legacy nodes must re-enrol")
	}
	if _, err := creds.SigningKey(); err != nil {
		return nil, err
	}
	return &creds, nil
}

func EnsureNonRoot() error {
	if os.Geteuid() == 0 {
		return errors.New("agentd must not run as root; use a dedicated non-root user")
	}
	return nil
}
