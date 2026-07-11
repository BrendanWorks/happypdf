# Builds the frontend and serves the static output. Talks to the backend
# container via VITE_API_URL (set at build time — Vite inlines env vars into
# the built bundle, so this must be passed as a build arg, not a runtime env var).
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM node:20-slim
WORKDIR /app
COPY --from=build /app/dist ./dist
# Isolated install (no copied package.json / devDependencies) so this stays
# pinned to exactly the vite version the project uses, not whatever npx would
# otherwise fetch on demand.
RUN npm init -y >/dev/null && npm install --no-save vite@5.4.2
EXPOSE 4173
CMD ["./node_modules/.bin/vite", "preview", "--host", "0.0.0.0", "--port", "4173"]
