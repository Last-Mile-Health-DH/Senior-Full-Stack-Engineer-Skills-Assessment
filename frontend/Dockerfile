FROM node:20-alpine

WORKDIR /app

# Install dependencies first so they're cached separately from app code changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "3000"]
