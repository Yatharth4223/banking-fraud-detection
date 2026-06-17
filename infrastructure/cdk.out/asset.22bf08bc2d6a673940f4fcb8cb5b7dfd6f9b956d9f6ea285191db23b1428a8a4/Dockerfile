FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-slim AS runner

WORKDIR /app

# 
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy build files from builder container
COPY --from=builder /root/.local /root/.local

# Copying Python API files, leaving out metadata
COPY ./app ./app

ENV PATH=/root/.local/bin:$PATH

# For container kernel security
RUN groupadd -r appgroup && useradd -r -g appgroup appuser && chown -R appuser:appgroup /app
USER appuser

#Exposed port
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]