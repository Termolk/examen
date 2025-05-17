// frontend/js/main.js

// Глобальные переменные для состояния на index.html
let currentCategoryId = null;
let currentPage = 1;
let currentSearchTerm = '';

// Глобальная переменная для данных текущего открытого объявления на listing-detail.html
let currentListingData = null;

// Глобальная переменная для файлов, выбранных на create-listing.html
let filesToUpload = [];

// (Опционально) Если решите использовать публичный доступ к Minio для картинок на главной
// const MINIO_PUBLIC_URL = 'http://localhost:9000'; // URL вашего Minio
// const MINIO_BUCKET_NAME = 'shareandrent-bucket'; // Имя бакета из конфига бэка

document.addEventListener('DOMContentLoaded', () => {
    // --- Логика для index.html ---
    if (document.getElementById('categoriesList') && document.getElementById('listingsGrid')) {
        loadCategories();
        loadListings(); // Загрузка всех объявлений по умолчанию

        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            let searchTimeout;
            searchInput.addEventListener('input', (e) => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    loadListings(1, e.target.value.trim(), currentCategoryId); // Передаем текущую категорию
                }, 500);
            });
        }
    }

    // --- Логика для listing-detail.html ---
    if (window.location.pathname.includes('listing-detail.html')) {
        const listingId = getQueryParam('id');
        if (listingId) {
            loadListingDetail(listingId);
        } else {
            const contentEl = document.getElementById('listingDetailContent');
            if (contentEl) contentEl.innerHTML = '<p class="text-danger text-center">ID объявления не указан.</p>';
            else console.error("Element with ID 'listingDetailContent' not found.");
        }
    }

    // --- Логика для create-listing.html ---
    if (window.location.pathname.includes('create-listing.html')) {
        if (!isLoggedIn()) {
            showAlert('Пожалуйста, войдите, чтобы разместить или редактировать объявление.', 'warning');
            setTimeout(() => window.location.href = 'login.html', 2000);
            return;
        }
        populateCategoriesDropdown();

        const editListingId = getQueryParam('edit_id');
        const pageTitleEl = document.getElementById('pageTitle');
        const submitButtonEl = document.getElementById('submitListingButton');
        const isActiveContainerEl = document.getElementById('isActiveContainer');


        if (editListingId) {
            if (pageTitleEl) pageTitleEl.textContent = 'Редактировать объявление';
            if (submitButtonEl) submitButtonEl.textContent = 'Сохранить изменения';
            if (isActiveContainerEl) isActiveContainerEl.style.display = 'block';
            loadListingForEditing(editListingId);
        } else {
            if (pageTitleEl) pageTitleEl.textContent = 'Создать новое объявление';
            if (submitButtonEl) submitButtonEl.textContent = 'Разместить объявление';
            if (isActiveContainerEl) isActiveContainerEl.style.display = 'none';
        }

        const listingForm = document.getElementById('listingForm');
        if (listingForm) listingForm.addEventListener('submit', handleListingFormSubmit);

        const imageInput = document.getElementById('images');
        if (imageInput) imageInput.addEventListener('change', previewImages);
    }

    // --- Логика для profile.html ---
    if (window.location.pathname.includes('profile.html')) {
        if (!isLoggedIn()) {
            showAlert('Пожалуйста, войдите, чтобы просмотреть профиль.', 'warning');
            setTimeout(() => window.location.href = 'login.html', 2000);
            return;
        }
        loadProfileData();

        const accordionItems = document.querySelectorAll('#profileAccordion .accordion-collapse');
        accordionItems.forEach(item => {
            item.addEventListener('show.bs.collapse', event => {
                const contentId = event.target.id.replace('Collapse', 'Content');
                const contentDiv = document.getElementById(contentId);
                if (contentDiv && contentDiv.innerHTML.toLowerCase().includes('загрузка')) {
                    if (contentId === 'myListingsContent') loadMyListings();
                    if (contentId === 'myBookingsContent') loadMyBookings();
                    if (contentId === 'bookingsOnMyListingsContent') loadBookingsOnMyListings();
                    if (contentId === 'myFavoritesContent') loadMyFavorites();
                    if (contentId === 'myReviewsContent') loadMyReviews();
                }
            });
        });
    }
});

// --- Функции для index.html ---
async function loadCategories() {
    const categoriesListEl = document.getElementById('categoriesList');
    if (!categoriesListEl) return;
    categoriesListEl.innerHTML = '<div class="list-group-item text-center"><div class="spinner-border spinner-border-sm" role="status"><span class="visually-hidden">Загрузка...</span></div></div>';

    const response = await request('/api/categories');
    if (response.success && Array.isArray(response.data)) {
        categoriesListEl.innerHTML = '';

        const allCategoriesButton = document.createElement('a');
        allCategoriesButton.href = '#';
        allCategoriesButton.classList.add('list-group-item', 'list-group-item-action', 'category-item');
        if (currentCategoryId === null) allCategoriesButton.classList.add('active');
        allCategoriesButton.textContent = 'Все категории';
        allCategoriesButton.addEventListener('click', (e) => {
            e.preventDefault();
            currentCategoryId = null;
            document.querySelectorAll('.category-item.active').forEach(el => el.classList.remove('active'));
            allCategoriesButton.classList.add('active');
            loadListings(1, currentSearchTerm);
        });
        categoriesListEl.appendChild(allCategoriesButton);

        response.data.forEach(category => renderCategoryItem(category, categoriesListEl, 0));
    } else {
        categoriesListEl.innerHTML = '<p class="text-danger list-group-item">Не удалось загрузить категории.</p>';
        showAlert(response.error || 'Ошибка загрузки категорий.');
    }
}

function renderCategoryItem(category, parentElement, depth) {
    const categoryEl = document.createElement('a');
    categoryEl.href = '#';
    categoryEl.classList.add('list-group-item', 'list-group-item-action', 'category-item');
    categoryEl.style.paddingLeft = `${1 + depth * 1.2}rem`; // Отступ для подкатегорий
    categoryEl.textContent = category.name;
    categoryEl.dataset.categoryId = category.id;

    if (parseInt(currentCategoryId) === category.id) categoryEl.classList.add('active');


    categoryEl.addEventListener('click', (e) => {
        e.preventDefault();
        currentCategoryId = category.id;
        document.querySelectorAll('.category-item.active').forEach(el => el.classList.remove('active'));
        categoryEl.classList.add('active');
        loadListings(1, currentSearchTerm, category.id);
    });
    parentElement.appendChild(categoryEl);

    if (category.subcategories && category.subcategories.length > 0) {
        category.subcategories.forEach(subCategory => {
            renderCategoryItem(subCategory, parentElement, depth + 1);
        });
    }
}


async function loadListings(page = 1, searchTerm = '', categoryId = null) {
    currentPage = page; // Обновляем глобальную текущую страницу
    if (searchTerm !== undefined) currentSearchTerm = searchTerm;
    if (categoryId !== undefined) currentCategoryId = categoryId;


    const listingsGridEl = document.getElementById('listingsGrid');
    if (!listingsGridEl) return;
    listingsGridEl.innerHTML = '<div class="d-flex justify-content-center mt-5 col-12"><div class="spinner-border" role="status"><span class="visually-hidden">Загрузка...</span></div></div>';

    let apiUrl = `/api/listings?page=${currentPage}&per_page=9`;
    if (currentSearchTerm) apiUrl += `&search=${encodeURIComponent(currentSearchTerm)}`;
    if (currentCategoryId) apiUrl += `&category_id=${currentCategoryId}`;

    const response = await request(apiUrl);
    if (response.success && response.data && Array.isArray(response.data.items)) {
        listingsGridEl.innerHTML = '';
        if (response.data.items.length === 0) {
            listingsGridEl.innerHTML = '<p class="text-center col-12">Объявлений не найдено.</p>';
        }
        response.data.items.forEach(listing => {
            // Используем presigned_url если он есть, иначе placeholder
            let imageUrl = 'https://via.placeholder.com/300x200.png?text=No+Image';
            if (listing.images && listing.images.length > 0) {
                // Бэкенд для /api/listings НЕ отдает presigned_url (в отличие от /api/listings/<id>)
                // Если бакет Minio публичный, можно было бы сделать так:
                // imageUrl = `${MINIO_PUBLIC_URL}/${MINIO_BUCKET_NAME}/${listing.images[0].image_url}`;
                // Пока что, если presigned_url нет, будет placeholder
                if(listing.images[0].presigned_url) {
                    imageUrl = listing.images[0].presigned_url;
                }
                // Если же в будущем бэкенд для /api/listings начнет отдавать presigned_url для главного фото:
                // imageUrl = listing.images[0].presigned_url || `MINIO_URL/BUCKET/${listing.images[0].image_url}` (с проверкой);
            }

            const listingCard = `
                <div class="col">
                    <div class="card h-100 listing-card">
                        <img src="${imageUrl}" class="card-img-top" alt="${listing.title}">
                        <div class="card-body d-flex flex-column">
                            <h5 class="card-title">${listing.title}</h5>
                            <p class="card-text"><small class="text-muted">${listing.category ? listing.category.name : 'Без категории'}</small></p>
                            <p class="card-text flex-grow-1">${listing.description ? listing.description.substring(0, 80) + (listing.description.length > 80 ? '...' : '') : 'Нет описания.'}</p>
                            <p class="card-text"><strong>Цена: ${parseFloat(listing.price_per_day).toFixed(2)} руб./день</strong></p>
                        </div>
                        <div class="card-footer">
                             <a href="listing-detail.html?id=${listing.id}" class="btn btn-primary btn-sm w-100">Подробнее</a>
                        </div>
                    </div>
                </div>
            `;
            listingsGridEl.insertAdjacentHTML('beforeend', listingCard);
        });
        setupPagination(response.data.page, response.data.pages, 'loadListings', { searchTerm: currentSearchTerm, categoryId: currentCategoryId });
    } else {
        listingsGridEl.innerHTML = '<p class="text-danger col-12 text-center">Не удалось загрузить объявления.</p>';
        showAlert(response.error || 'Ошибка загрузки объявлений.');
    }
}

function setupPagination(currentPage, totalPages, callbackFunctionName, callbackArgs = {}) {
    const paginationControls = document.getElementById('paginationControls');
    if (!paginationControls) return;
    paginationControls.innerHTML = '';

    if (totalPages <= 1) return;

    function createPageItem(pageNumber, text, isDisabled, isActive) {
        const li = document.createElement('li');
        li.classList.add('page-item');
        if (isDisabled) li.classList.add('disabled');
        if (isActive) li.classList.add('active');

        const a = document.createElement('a');
        a.classList.add('page-link');
        a.href = '#';
        a.textContent = text || pageNumber;
        if (!isDisabled) {
            a.addEventListener('click', (e) => {
                e.preventDefault();
                // Динамический вызов функции пагинации
                if (typeof window[callbackFunctionName] === 'function') {
                     window[callbackFunctionName](pageNumber, callbackArgs.searchTerm, callbackArgs.categoryId);
                } else if (typeof window[callbackFunctionName] === 'function' && callbackArgs.listingId) { // для пагинации отзывов
                     window[callbackFunctionName](callbackArgs.listingId, pageNumber);
                }
            });
        }
        li.appendChild(a);
        return li;
    }

    paginationControls.appendChild(createPageItem(currentPage - 1, '‹', currentPage === 1));

    // Логика для отображения ограниченного числа страниц (например, 1 ... 3 4 5 ... 10)
    const delta = 2; // Сколько страниц показывать до и после текущей
    const range = [];
    for (let i = Math.max(2, currentPage - delta); i <= Math.min(totalPages - 1, currentPage + delta); i++) {
        range.push(i);
    }

    if (currentPage - delta > 2) range.unshift('...');
    if (currentPage + delta < totalPages - 1) range.push('...');

    range.unshift(1);
    if (totalPages > 1) range.push(totalPages);

    range.forEach(page => {
        if (page === '...') {
            const li = document.createElement('li');
            li.classList.add('page-item', 'disabled');
            const span = document.createElement('span');
            span.classList.add('page-link');
            span.textContent = '...';
            li.appendChild(span);
            paginationControls.appendChild(li);
        } else {
            paginationControls.appendChild(createPageItem(page, null, false, page === currentPage));
        }
    });
    paginationControls.appendChild(createPageItem(currentPage + 1, '›', currentPage === totalPages));
}


// --- Функции для listing-detail.html ---
async function loadListingDetail(listingId) {
    const contentEl = document.getElementById('listingDetailContent');
    if (!contentEl) { console.error("Element 'listingDetailContent' not found."); return; }
    contentEl.innerHTML = '<div class="col-12 text-center mt-5"><div class="spinner-border" role="status"><span class="visually-hidden">Загрузка...</span></div></div>';

    const response = await request(`/api/listings/${listingId}`);
    if (response.success && response.data) {
        currentListingData = response.data;
        contentEl.innerHTML = '';

        const listing = response.data;
        let imagesHtml = '<p class="text-center">Нет изображений.</p>';
        if (listing.images && listing.images.length > 0) {
            imagesHtml = `
                <div id="listingCarousel" class="carousel slide mb-3" data-bs-ride="carousel">
                    <div class="carousel-indicators">
                        ${listing.images.map((img, index) => `<button type="button" data-bs-target="#listingCarousel" data-bs-slide-to="${index}" class="${index === 0 ? 'active' : ''}" aria-current="${index === 0 ? 'true' : 'false'}" aria-label="Slide ${index + 1}"></button>`).join('')}
                    </div>
                    <div class="carousel-inner">
                        ${listing.images.map((img, index) => `<div class="carousel-item ${index === 0 ? 'active' : ''}"><img src="${img.presigned_url || 'https://via.placeholder.com/800x400.png?text=Image+Not+Available'}" class="d-block w-100" style="max-height: 450px; object-fit: contain;" alt="${listing.title} image ${index + 1}"></div>`).join('')}
                    </div>
                    ${listing.images.length > 1 ? `<button class="carousel-control-prev" type="button" data-bs-target="#listingCarousel" data-bs-slide="prev"><span class="carousel-control-prev-icon" aria-hidden="true"></span><span class="visually-hidden">Previous</span></button><button class="carousel-control-next" type="button" data-bs-target="#listingCarousel" data-bs-slide="next"><span class="carousel-control-next-icon" aria-hidden="true"></span><span class="visually-hidden">Next</span></button>` : ''}
                </div>`;
        }

        const detailHtml = `
            <div class="col-lg-8">
                ${imagesHtml}
                <h1 class="mb-3">${listing.title}</h1>
                <p class="text-muted">Категория: ${listing.category ? listing.category.name : 'N/A'}</p>
                <p style="white-space: pre-wrap;">${listing.description || 'Нет описания.'}</p>
            </div>
            <div class="col-lg-4">
                <div class="card sticky-top" style="top: 20px;">
                    <div class="card-body">
                        <h4 class="card-title">Цена: ${parseFloat(listing.price_per_day).toFixed(2)} руб./день</h4>
                        <p class="card-text mb-2">Владелец: ${listing.owner ? listing.owner.username : 'N/A'}</p>
                        <div id="favoriteButtonContainer" class="d-grid gap-2 mb-2"></div>
                        <div id="editListingButtonContainer" class="d-grid gap-2"></div>
                    </div>
                </div>
            </div>`;
        contentEl.innerHTML = detailHtml;

        updateFavoriteButtonState(listingId);
        setupBookingForm(listingId);
        setupReviewForm(listingId);
        loadReviewsTab(listingId); // Загрузка отзывов (для отдельной вкладки или секции)
        setupEditListingButton(listingId);
    } else {
        contentEl.innerHTML = `<p class="text-danger text-center">${response.error || 'Не удалось загрузить детали объявления.'}</p>`;
        showAlert(response.error || 'Ошибка загрузки объявления.');
    }
}

async function updateFavoriteButtonState(listingId) {
    const favButtonContainer = document.getElementById('favoriteButtonContainer');
    if (!favButtonContainer) return;
    favButtonContainer.innerHTML = ''; // Clear previous button

    if (!isLoggedIn()) {
        // Можно не показывать кнопку или показывать, но с предложением войти
        return;
    }

    const favResponse = await request('/api/my-favorites'); // Запрос на бэкенд для получения списка избранного
    let isFavorited = false;
    if (favResponse.success && Array.isArray(favResponse.data)) {
        isFavorited = favResponse.data.some(fav => fav.listing && fav.listing.id === parseInt(listingId));
    }

    const favoriteButton = document.createElement('button');
    favoriteButton.id = 'favoriteButton';
    favoriteButton.classList.add('btn', 'btn-sm', 'w-100');
    if (isFavorited) {
        favoriteButton.innerHTML = '<i class="bi bi-heart-fill"></i> В избранном';
        favoriteButton.classList.add('btn-danger');
    } else {
        favoriteButton.innerHTML = '<i class="bi bi-heart"></i> Добавить в избранное';
        favoriteButton.classList.add('btn-outline-danger');
    }

    favoriteButton.addEventListener('click', async () => {
        const response = await request(`/api/listings/${listingId}/favorite`, 'POST');
        if (response.success) {
            showAlert(response.data.msg || 'Статус избранного обновлен.', 'success');
            updateFavoriteButtonState(listingId); // Обновить вид кнопки
        } else {
            showAlert(response.error || 'Не удалось обновить статус избранного.', 'danger');
        }
    });
    favButtonContainer.appendChild(favoriteButton);
}

function setupBookingForm(listingId) {
    const bookingSection = document.getElementById('bookingSection');
    const bookingForm = document.getElementById('bookingForm');
    const ownerPhoneNumberEl = document.getElementById('ownerPhoneNumber');
    const phoneTextEl = document.getElementById('phoneText');

    if (!bookingForm || !bookingSection || !currentListingData) return;

    if (isLoggedIn() && currentListingData.owner && currentListingData.owner.id !== getCurrentUserId()) {
        bookingSection.style.display = 'block';
    } else {
        bookingSection.style.display = 'none';
        return;
    }

    const today = new Date().toISOString().split('T')[0];
    const startDateInput = document.getElementById('startDate');
    const endDateInput = document.getElementById('endDate');
    if(startDateInput) startDateInput.setAttribute('min', today);
    if(endDateInput) endDateInput.setAttribute('min', today);

    bookingForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const startDate = startDateInput.value;
        const endDate = endDateInput.value;

        if (!startDate || !endDate) { showAlert('Пожалуйста, выберите даты начала и окончания.', 'warning'); return; }
        if (new Date(endDate) < new Date(startDate)) { showAlert('Дата окончания не может быть раньше даты начала.', 'warning'); return; }

        const response = await request(`/api/listings/${listingId}/book`, 'POST', { start_date: startDate, end_date: endDate });
        if (response.success) {
            showAlert('Объявление успешно забронировано!', 'success');
            if (phoneTextEl && ownerPhoneNumberEl && response.data.owner_phone_number) {
                phoneTextEl.textContent = response.data.owner_phone_number;
                ownerPhoneNumberEl.style.display = 'block';
            }
            bookingForm.reset();
        } else {
            showAlert(response.error || 'Не удалось забронировать.', 'danger');
        }
    });
}

function getCurrentUserId() {
    const token = getAccessToken();
    if (!token) return null;
    try {
        const payloadBase64Url = token.split('.')[1];
        const payloadBase64 = payloadBase64Url.replace(/-/g, '+').replace(/_/g, '/');
        const payloadJson = decodeURIComponent(atob(payloadBase64).split('').map(function(c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join(''));
        const payload = JSON.parse(payloadJson);
        return payload.sub;
    } catch (e) {
        console.error("Error decoding token for user ID:", e);
        clearTokens(); // Если токен невалиден, лучше его удалить
        return null;
    }
}

async function loadReviewsTab(listingId, page = 1) { // Переименовал, т.к. это для секции "Отзывы"
    const reviewsListEl = document.getElementById('reviewsList');
    const reviewsCountEl = document.getElementById('reviewsCount');
    if (!reviewsListEl || !reviewsCountEl) return;

    reviewsListEl.innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm" role="status"><span class="visually-hidden">Загрузка...</span></div></div>';

    // Загружаем отзывы с пагинацией через отдельный эндпоинт
    const response = await request(`/api/listings/${listingId}/reviews?page=${page}&per_page=5`);

    if (response.success && response.data && Array.isArray(response.data.items)) {
        const reviews = response.data.items;
        reviewsCountEl.textContent = response.data.total || 0;
        if (reviews.length === 0 && response.data.total === 0) {
            reviewsListEl.innerHTML = '<p class="list-group-item">Отзывов пока нет.</p>';
            return;
        }
        reviewsListEl.innerHTML = '';
        reviews.forEach(review => {
            const reviewHtml = `
                <div class="list-group-item">
                    <div class="d-flex w-100 justify-content-between">
                        <h6 class="mb-1">${review.reviewer ? review.reviewer.username : 'Аноним'}</h6>
                        <small class="text-muted">${new Date(review.created_at).toLocaleDateString()}</small>
                    </div>
                    <p class="mb-1 small">Оценка: ${'★'.repeat(review.rating)}${'☆'.repeat(5 - review.rating)}</p>
                    <p class="mb-0 small fst-italic">${review.comment || ''}</p>
                </div>`;
            reviewsListEl.insertAdjacentHTML('beforeend', reviewHtml);
        });
        // Добавляем пагинацию для отзывов, если есть
        const paginationContainer = document.createElement('div');
        paginationContainer.id = 'reviewsPaginationControls'; // Уникальный ID для пагинации отзывов
        paginationContainer.classList.add('mt-3');
        reviewsListEl.insertAdjacentElement('afterend', paginationContainer.previousElementSibling === reviewsListEl ? paginationContainer : paginationContainer); // Вставляем после списка отзывов

        // Удаляем старую пагинацию отзывов, если она была
        const oldReviewsPagination = document.getElementById('reviewsPaginationControls');
        if(oldReviewsPagination && oldReviewsPagination.parentElement !== reviewsListEl.parentElement) oldReviewsPagination.remove();

        if (response.data.pages > 1) {
            const reviewPaginationTarget = document.createElement('ul');
            reviewPaginationTarget.id = 'reviewsPaginationControlsActual';
            reviewPaginationTarget.classList.add('pagination', 'pagination-sm', 'justify-content-center');
            reviewsListEl.insertAdjacentElement('afterend', reviewPaginationTarget);
            setupPagination(response.data.page, response.data.pages, 'loadReviewsTab', { listingId: listingId });
            // Важно: setupPagination теперь должен уметь работать с `reviewsPaginationControlsActual`
            // Передадим ID контейнера пагинации в setupPagination или сделаем его более гибким
        }


    } else {
        reviewsListEl.innerHTML = '<p class="list-group-item text-danger">Не удалось загрузить отзывы.</p>';
         showAlert(response.error || 'Ошибка загрузки отзывов.');
    }
}


function setupReviewForm(listingId) {
    const addReviewSection = document.getElementById('addReviewSection');
    const reviewForm = document.getElementById('reviewForm');
    if (!reviewForm || !addReviewSection || !currentListingData) return;

    if (isLoggedIn() && currentListingData.owner && currentListingData.owner.id !== getCurrentUserId()) {
        addReviewSection.style.display = 'block';
    } else {
        addReviewSection.style.display = 'none';
        return;
    }

    reviewForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const rating = document.getElementById('rating').value;
        const comment = document.getElementById('comment').value;
        const response = await request(`/api/listings/${listingId}/reviews`, 'POST', { rating: parseInt(rating), comment: comment });
        if (response.success) {
            showAlert('Спасибо за ваш отзыв!', 'success');
            reviewForm.reset();
            loadReviewsTab(listingId); // Перезагружаем отзывы с первой страницы
        } else {
            showAlert(response.error || 'Не удалось отправить отзыв. Возможно, вы уже оставляли отзыв на это объявление.', 'danger');
        }
    });
}

function setupEditListingButton(listingId) {
    const container = document.getElementById('editListingButtonContainer');
    if (!container || !currentListingData) return;
    container.innerHTML = ''; // Очищаем

    if (isLoggedIn() && currentListingData.owner && currentListingData.owner.id === getCurrentUserId()) {
        const editButton = document.createElement('a');
        editButton.href = `create-listing.html?edit_id=${listingId}`;
        editButton.classList.add('btn', 'btn-secondary', 'btn-sm', 'w-100');
        editButton.textContent = 'Редактировать объявление';
        container.appendChild(editButton);
    }
}

// --- Функции для create-listing.html ---
async function populateCategoriesDropdown() {
    const categorySelect = document.getElementById('category');
    if (!categorySelect) return;
    categorySelect.innerHTML = '<option value="">Загрузка категорий...</option>';

    const response = await request('/api/categories');
    if (response.success && Array.isArray(response.data)) {
        categorySelect.innerHTML = '<option value="">Выберите категорию...</option>';
        response.data.forEach(category => addCategoryOptions(category, categorySelect, 0));
    } else {
        categorySelect.innerHTML = '<option value="">Ошибка загрузки</option>';
        showAlert('Не удалось загрузить категории.', 'danger');
    }
}

function addCategoryOptions(category, selectElement, depth) { // Уже есть такая функция, но пусть будет здесь для контекста create-listing
    const option = document.createElement('option');
    option.value = category.id;
    option.textContent = `${'— '.repeat(depth)}${category.name}`;
    selectElement.appendChild(option);
    if (category.subcategories && category.subcategories.length > 0) {
        category.subcategories.forEach(subCategory => addCategoryOptions(subCategory, selectElement, depth + 1));
    }
}

function previewImages(event) {
    const previewContainer = document.getElementById('imagePreviewContainer');
    if (!previewContainer) return;
    previewContainer.innerHTML = '';
    filesToUpload = Array.from(event.target.files);

    if (filesToUpload.length > 5) {
        showAlert('Можно загрузить не более 5 изображений.', 'warning');
        event.target.value = ''; filesToUpload = []; return;
    }

    filesToUpload.forEach(file => {
        const reader = new FileReader();
        reader.onload = e => {
            const imgEl = document.createElement('img');
            imgEl.src = e.target.result;
            imgEl.className = 'img-thumbnail m-1';
            imgEl.style.width = '100px'; imgEl.style.height = '100px'; imgEl.style.objectFit = 'cover';
            previewContainer.appendChild(imgEl);
        }
        reader.readAsDataURL(file);
    });
}

async function handleListingFormSubmit(event) {
    event.preventDefault();
    if (!isLoggedIn()) { showAlert('Пожалуйста, войдите.', 'danger'); return; }

    const listingId = document.getElementById('listingId').value;
    const isEditMode = !!listingId;
    const submitButton = document.getElementById('submitListingButton');
    submitButton.disabled = true;
    submitButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Сохранение...';


    const listingData = {
        title: document.getElementById('title').value,
        description: document.getElementById('description').value,
        category_id: parseInt(document.getElementById('category').value),
        price_per_day: parseFloat(document.getElementById('price').value),
        phone_number: document.getElementById('phoneNumber').value,
    };
    if (isEditMode) listingData.is_active = document.getElementById('isActive').checked;

    const response = isEditMode ?
        await request(`/api/listings/${listingId}`, 'PUT', listingData) :
        await request('/api/listings', 'POST', listingData);

    if (response.success && response.data && response.data.id) {
        const currentListingId = response.data.id;
        showAlert(isEditMode ? 'Объявление успешно обновлено!' : 'Объявление успешно создано!', 'success');

        if (filesToUpload.length > 0) {
            const formData = new FormData();
            filesToUpload.forEach(file => formData.append('image', file));

            const imageUploadResponse = await request(`/api/listings/${currentListingId}/images`, 'POST', formData, true); // formData, не JSON
            if (imageUploadResponse.success) {
                showAlert('Изображения успешно загружены!', 'info');
            } else {
                showAlert(imageUploadResponse.error || 'Ошибка загрузки изображений.', 'danger');
            }
        }
        filesToUpload = []; // Очищаем после загрузки
        setTimeout(() => window.location.href = `listing-detail.html?id=${currentListingId}`, 1500);
    } else {
        showAlert(response.error || (isEditMode ? 'Ошибка обновления.' : 'Ошибка создания.'), 'danger');
    }
    submitButton.disabled = false;
    submitButton.innerHTML = isEditMode ? 'Сохранить изменения' : 'Разместить объявление';
}

async function loadListingForEditing(listingId) {
    const response = await request(`/api/listings/${listingId}`);
    if (response.success && response.data) {
        const listing = response.data;
        document.getElementById('listingId').value = listing.id;
        document.getElementById('title').value = listing.title;
        document.getElementById('description').value = listing.description || '';
        // Установка категории после того, как они загружены
        const categorySelect = document.getElementById('category');
        if (categorySelect.options.length > 1) { // Если категории уже загружены
             categorySelect.value = listing.category ? listing.category.id : '';
        } else { // Если нет, ждем их загрузки и потом устанавливаем
            categorySelect.addEventListener('categoriesLoaded', () => { // Кастомное событие
                 categorySelect.value = listing.category ? listing.category.id : '';
            }, { once: true });
        }
        document.getElementById('price').value = parseFloat(listing.price_per_day).toFixed(2);
        document.getElementById('phoneNumber').value = listing.phone_number;
        if(document.getElementById('isActive')) document.getElementById('isActive').checked = listing.is_active;

        const imagePreviewContainer = document.getElementById('imagePreviewContainer');
        if (imagePreviewContainer) {
            imagePreviewContainer.innerHTML = '<small class="text-muted col-12">Существующие изображения будут сохранены. Вы можете добавить новые. Для управления существующими изображениями перейдите на страницу объявления.</small>';
             if (listing.images && listing.images.length > 0) {
                listing.images.forEach(img => {
                    const imgEl = document.createElement('img');
                    imgEl.src = img.presigned_url || `${MINIO_PUBLIC_URL}/${MINIO_BUCKET_NAME}/${img.image_url}`; // Пример с публичным URL если нет presigned
                    imgEl.className = 'img-thumbnail m-1 opacity-50'; // Слегка затемняем старые
                    imgEl.style.width = '80px'; imgEl.style.height = '80px'; imgEl.style.objectFit = 'cover';
                    imagePreviewContainer.appendChild(imgEl);
                });
            }
        }

    } else {
        showAlert('Не удалось загрузить данные объявления для редактирования.', 'danger');
        setTimeout(() => window.location.href = 'index.html', 2000);
    }
}
// Для установки значения категории после их асинхронной загрузки в режиме редактирования:
// Внутри populateCategoriesDropdown, после цикла forEach:
// categorySelect.dispatchEvent(new Event('categoriesLoaded'));


// --- Функции для profile.html ---
async function loadProfileData() {
    const usernameEl = document.getElementById('profileUsername');
    if (!usernameEl) return;
    const token = getAccessToken();
    if (token) {
        try {
            const protectedResp = await request('/auth/protected');
            if (protectedResp.success && protectedResp.data.logged_in_as) {
                usernameEl.textContent = protectedResp.data.logged_in_as;
            } else { usernameEl.textContent = 'Пользователь'; }
        } catch (e) { usernameEl.textContent = 'Пользователь'; }
    }
}

async function loadMyListings() {
    const contentDiv = document.getElementById('myListingsContent');
    if (!contentDiv) return;
    contentDiv.innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm" role="status"></div></div>';
    // Предполагаем, что бэкенд отдает все объявления, и мы фильтруем.
    // В идеале, нужен эндпоинт типа /api/me/listings или /api/listings?owner_id=me
    const response = await request('/api/listings?per_page=200'); // Загружаем побольше для фильтрации
    const currentUserIdVal = getCurrentUserId();

    if (response.success && response.data && Array.isArray(response.data.items)) {
        const myListings = response.data.items.filter(l => l.owner && l.owner.id === currentUserIdVal);
        if (myListings.length === 0) { contentDiv.innerHTML = '<p>У вас пока нет объявлений. <a href="create-listing.html">Создать новое?</a></p>'; return; }
        let html = '<ul class="list-group list-group-flush">';
        myListings.forEach(l => {
            html += `<li class="list-group-item d-flex justify-content-between align-items-center">
                        <div>
                           <a href="listing-detail.html?id=${l.id}">${l.title}</a>
                           <span class="badge bg-${l.is_active ? 'success' : 'secondary'} ms-2">${l.is_active ? 'Активно' : 'Неактивно'}</span>
                        </div>
                        <a href="create-listing.html?edit_id=${l.id}" class="btn btn-sm btn-outline-primary">Редактировать</a>
                     </li>`;
        });
        html += '</ul>';
        contentDiv.innerHTML = html;
    } else { contentDiv.innerHTML = '<p class="text-danger">Не удалось загрузить ваши объявления.</p>'; }
}

async function loadMyBookings() {
    const contentDiv = document.getElementById('myBookingsContent');
    if (!contentDiv) return;
    contentDiv.innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm" role="status"></div></div>';
    const response = await request('/api/my-bookings');
    if (response.success && Array.isArray(response.data)) {
        if (response.data.length === 0) { contentDiv.innerHTML = '<p>У вас нет активных бронирований.</p>'; return; }
        let html = '<ul class="list-group list-group-flush">';
        response.data.forEach(b => {
            html += `<li class="list-group-item">
                        Объявление: <strong><a href="listing-detail.html?id=${b.listing.id}">${b.listing.title}</a></strong><br>
                        Даты: ${new Date(b.start_date).toLocaleDateString()} - ${new Date(b.end_date).toLocaleDateString()}
                        ${b.listing.phone_number ? `<br><small class="text-muted">Тел. владельца: ${b.listing.phone_number}</small>` : ''}
                     </li>`;
        });
        html += '</ul>';
        contentDiv.innerHTML = html;
    } else { contentDiv.innerHTML = '<p class="text-danger">Не удалось загрузить ваши бронирования.</p>'; }
}

async function loadBookingsOnMyListings() {
    const contentDiv = document.getElementById('bookingsOnMyListingsContent');
    if (!contentDiv) return;
    contentDiv.innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm" role="status"></div></div>';
    const response = await request('/api/my-listings-bookings');
    if (response.success && Array.isArray(response.data)) {
        if (response.data.length === 0) { contentDiv.innerHTML = '<p>На ваши объявления пока нет бронирований.</p>'; return; }
        let html = '<ul class="list-group list-group-flush">';
        response.data.forEach(b => {
            html += `<li class="list-group-item">
                        Объявление: <strong><a href="listing-detail.html?id=${b.listing.id}">${b.listing.title}</a></strong><br>
                        Забронировал: ${b.renter.username}<br>
                        Даты: ${new Date(b.start_date).toLocaleDateString()} - ${new Date(b.end_date).toLocaleDateString()}
                     </li>`;
        });
        html += '</ul>';
        contentDiv.innerHTML = html;
    } else { contentDiv.innerHTML = '<p class="text-danger">Не удалось загрузить бронирования на ваши объявления.</p>'; }
}

async function loadMyFavorites() {
    const contentDiv = document.getElementById('myFavoritesContent');
    if (!contentDiv) return;
    contentDiv.innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm" role="status"></div></div>';
    const response = await request('/api/my-favorites');
    if (response.success && Array.isArray(response.data)) {
        if (response.data.length === 0) { contentDiv.innerHTML = '<p>У вас нет избранных объявлений.</p>'; return; }
        let html = '<div class="row row-cols-1 row-cols-sm-2 row-cols-md-3 g-3">';
        response.data.forEach(fav => {
            const listing = fav.listing;
            if (!listing) return; // Проверка на случай если данные неполные
            let imageUrl = 'https://via.placeholder.com/300x200.png?text=No+Image';
            if (listing.images && listing.images.length > 0) { // Предполагаем, что бэк для /my-favorites отдает presigned_url
                 imageUrl = listing.images[0].presigned_url || imageUrl;
            }
            html += `
                <div class="col">
                    <div class="card h-100">
                         <img src="${imageUrl}" class="card-img-top" alt="${listing.title}" style="height: 150px; object-fit: cover;">
                        <div class="card-body">
                            <h6 class="card-title mb-1">${listing.title}</h6>
                             <a href="listing-detail.html?id=${listing.id}" class="btn btn-sm btn-outline-primary mt-auto">Подробнее</a>
                        </div>
                    </div>
                </div>`;
        });
        html += '</div>';
        contentDiv.innerHTML = html;
    } else { contentDiv.innerHTML = '<p class="text-danger">Не удалось загрузить избранное.</p>'; }
}

async function loadMyReviews() {
    const contentDiv = document.getElementById('myReviewsContent');
    if (!contentDiv) return;
    contentDiv.innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm" role="status"></div></div>';
    const response = await request('/api/my-reviews');
    if (response.success && Array.isArray(response.data)) {
        if (response.data.length === 0) { contentDiv.innerHTML = '<p>Вы пока не оставили ни одного отзыва.</p>'; return; }
        let html = '<ul class="list-group list-group-flush">';
        response.data.forEach(r => {
            html += `<li class="list-group-item">
                        Объявление: <strong><a href="listing-detail.html?id=${r.listing.id}">${r.listing.title}</a></strong><br>
                        Оценка: <span class="text-warning">${'★'.repeat(r.rating)}${'☆'.repeat(5 - r.rating)}</span><br>
                        <small class="d-block fst-italic text-muted">${r.comment || 'Без комментария.'}</small>
                     </li>`;
        });
        html += '</ul>';
        contentDiv.innerHTML = html;
    } else { contentDiv.innerHTML = '<p class="text-danger">Не удалось загрузить ваши отзывы.</p>'; }
}

// Дополнение для populateCategoriesDropdown, чтобы диспатчить событие
// Внутри populateCategoriesDropdown, после цикла forEach:
// if (response.success && Array.isArray(response.data)) { ... categorySelect.dispatchEvent(new Event('categoriesLoaded')); }
// Это нужно для того, чтобы loadListingForEditing мог дождаться загрузки категорий.
// Изменим populateCategoriesDropdown:
async function populateCategoriesDropdown() { // Переопределяем для добавления события
    const categorySelect = document.getElementById('category');
    if (!categorySelect) return;
    categorySelect.innerHTML = '<option value="">Загрузка категорий...</option>';

    const response = await request('/api/categories');
    if (response.success && Array.isArray(response.data)) {
        categorySelect.innerHTML = '<option value="">Выберите категорию...</option>';
        response.data.forEach(category => addCategoryOptions(category, categorySelect, 0)); // addCategoryOptions уже определена выше
        categorySelect.dispatchEvent(new Event('categoriesLoaded')); // Диспатчим событие
    } else {
        categorySelect.innerHTML = '<option value="">Ошибка загрузки</option>';
        showAlert('Не удалось загрузить категории.', 'danger');
    }
}