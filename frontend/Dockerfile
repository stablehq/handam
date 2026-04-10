# Stage 1: 빌드
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_SENTRY_DSN=""
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
RUN npm run build

# Stage 2: nginx 서빙
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY nginx-init.conf /etc/nginx/conf.d/nginx-init.conf.template
COPY nginx-ssl.conf /etc/nginx/conf.d/nginx-ssl.conf.template
EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
