# Adapters

[![Conformance Matrix](https://img.shields.io/badge/Ports%20Conformance-100%25-brightgreen.svg)](https://github.com/incident-response-mesh/incident-response-mesh)

This package contains the production-grade infrastructure adapters for the Incident Response Mesh:

- **Queue**: Redis Streams (`RedisStreamQueue`)
- **LockService**: Redis (`RedisLockService`)
- **AuditSink**: PostgreSQL (`PgAuditSink`)
- **BlobStore**: Filesystem (`FsBlobStore`)
- **SecretStore**: Environment Variables (`EnvSecretStore`)

All adapters have been verified against the strict hexagon contracts provided by `ports-testing`.
