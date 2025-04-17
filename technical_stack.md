# Fedow - Technical Stack and Development Methods

## Overview

Fedow (Federated & Open Wallet Engine) is an open-source federation engine, blockchain, and digital wallet designed to
connect cashless payment systems, local currencies, and memberships across multiple venues, festivals, and cooperative
networks. This document outlines the technical stack and development methods used in the Fedow project.

## Technical Stack

### Backend

- **Programming Language**: Python 3.10+
- **Web Framework**: Django 4.2
- **API Framework**: Django REST Framework
- **Database**: SQLite (development), PostgreSQL (production)
- **Caching**: Memcached
- **Authentication**:
    - API Key-based authentication (djangorestframework-api-key)
    - RSA signature-based authentication
- **Payment Processing**: Stripe API
- **Cryptography**:
    - RSA for asymmetric encryption and signatures
    - Fernet for symmetric encryption
- **Task Queue**: None identified (potential future addition)

### Frontend

- **Dashboard**: HTML/CSS/JavaScript with Bootstrap 5
- **Interactive UI**: HTMX for dynamic content without full page reloads
- **CSS Framework**: Bootstrap 5.2.3

### DevOps & Deployment

- **Containerization**: Docker
- **Orchestration**: Docker Compose
- **Web Server**: Nginx
- **Application Server**: Gunicorn
- **CI/CD**: GitHub Actions
- **Monitoring**: Sentry
- **Version Control**: Git

### Key Dependencies

- django-solo: For singleton models
- django-extensions: For additional Django utilities
- django-stdimage: For image handling
- cryptography: For encryption and signature operations
- channels: For WebSocket support
- faker: For generating test data
- python-dotenv: For environment variable management

## Architecture

### Core Components

1. **Blockchain System**:
    - Uses Proof of Authority (PoA) for consensus
    - Transaction validation with hash verification
    - Non-speculative design focused on traceability

2. **Wallet Management**:
    - Multi-asset wallets (currencies, time, memberships)
    - RSA key pairs for wallet security
    - Support for ephemeral wallets

3. **Federation System**:
    - Connects multiple venues and networks
    - Shared assets across federated places
    - Centralized configuration with distributed operation

4. **Card Management**:
    - Support for NFC/RFID/QRCode cards
    - Card linking to wallets
    - Primary cards for venues

5. **Payment Processing**:
    - Stripe integration for fiat currency handling
    - Support for local currencies
    - Refund capabilities

### Data Model

The core data model revolves around:

- **Wallet**: Container for tokens, linked to users or places
- **Asset**: Represents a currency, membership, or time unit
- **Token**: Represents a specific amount of an asset in a wallet
- **Transaction**: Records transfers between wallets
- **Federation**: Groups places and assets for interoperability
- **Place**: Represents a venue or organization
- **Card**: Physical or virtual card linked to a wallet

## Development Methods

### Code Organization

- **MVC Pattern**: Following Django's Model-View-Template pattern
- **API-First Design**: RESTful API with comprehensive serializers
- **Permission-Based Access Control**: Fine-grained permissions for API endpoints

### Security Practices

- **Cryptographic Signatures**: For API request authentication
- **API Key Management**: For service-to-service authentication
- **Secure Data Storage**: Encryption for sensitive data
- **Input Validation**: Comprehensive validation in serializers

### Testing

- **Unit Tests**: Using Django's testing framework
- **Coverage Tracking**: Using the coverage package
- **Test Data Generation**: Using Faker for realistic test data

### Development Workflow

- **Environment Isolation**: Using Docker for consistent development environments
- **Dependency Management**: Using Poetry for Python package management
- **Configuration Management**: Using environment variables and .env files

## Integration Points

### External Services

- **Stripe**: For payment processing
- **Sentry**: For error tracking

### Internal Ecosystem

Fedow is part of a suite of interoperable tools:

- **Lespass**: Ticketing, memberships, landing pages
- **LaBoutik**: Cash register, cashless, order management
