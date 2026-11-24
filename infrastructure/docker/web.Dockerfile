# Manima One web (Next.js standalone output).
FROM node:24-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
# API_URL is read by next.config.ts rewrites at build time and at runtime.
ARG API_URL=http://api:8000
ENV API_URL=$API_URL
RUN npm run build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 web && adduser -S -u 10001 -G web web
COPY --from=build --chown=web:web /app/.next/standalone ./
COPY --from=build --chown=web:web /app/.next/static ./.next/static
USER web
EXPOSE 3000
CMD ["node", "server.js"]
