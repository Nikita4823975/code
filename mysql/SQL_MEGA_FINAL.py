import mysql.connector
from fpdf import FPDF
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import messagebox, simpledialog, Toplevel
import os
import threading
from queue import Queue
from ttkbootstrap import Style
from datetime import datetime

# Словарь для сопоставления имен пользователей с их ролями
user_roles = {
    'nikita': 'administrator',
    'megan': 'manager',
    'joe': 'seller',
    'root': 'root'
}


# Функция подключения к базе данных
def connect_to_db(user, password):
    try:
        cnx = mysql.connector.connect(
            user=user,
            password=password,
            host="localhost",
            database="kurs",
            use_unicode=True,
            charset="utf8"
        )
        return cnx
    except mysql.connector.Error as err:
        messagebox.showerror("Ошибка", f"Ошибка подключения к базе данных: {err}")
        return None


def center_window(window, width, height):
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width / 2) - (width / 2)
    y = (screen_height / 2) - (height / 2)
    window.geometry(f'{width}x{height}+{int(x)}+{int(y)}')


# Функция генерации статистики по серверам
def generate_server_statistics(cnx, order_by, error_queue):
    try:
        cursor = cnx.cursor()
        query = f"""
            SELECT 
                s.ID_Server,
                s.Adress,
                s.City,
                m.ModelName AS ServerModel,
                s.StorageLeft,
                s.MonthlyRentCost,
                e.Surname AS TechnicianSurname,
                e.Name AS TechnicianName
            FROM 
                servers s
            JOIN 
                models m ON s.Model_ID = m.ID_Model
            JOIN 
                employees e ON s.Technician_ID = e.ID_Employee
            ORDER BY s.ID_Server {order_by};
        """
        cursor.execute(query)
        data = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        cursor.close()  # Закрываем курсор после использования

        pdf = FPDF()
        pdf.add_page()
        pdf.add_font("DejaVuSans", "", "DejaVuSans.ttf", uni=True)
        pdf.set_font("DejaVuSans", size=12)
        pdf.cell(200, 10, txt="Статистика по серверам", ln=True, align='C')

        pdf.set_font("DejaVuSans", size=12)
        for col in columns:
            pdf.cell(40, 10, txt=col, border=1, align='C')
        pdf.ln(10)

        for row in data:
            for cell in row:
                pdf.cell(40, 10, txt=str(cell), border=1, align='C')
            pdf.ln(10)

        pdf.output("server_statistics.pdf")
        os.startfile("server_statistics.pdf")
    except Exception as e:
        error_queue.put(e)


# Функция генерации договора аренды
def generate_rental_contract(cnx, contract_id, error_queue):
    try:
        cursor = cnx.cursor()

        # Получение данных из базы данных
        query = f"""
            SELECT 
                c.ID_Contracts,
                ri.Surname AS RenterSurname,
                ri.Name AS RenterName,
                rl.Name AS RenterLegalName,
                c.RentedSpace,
                c.MonthlyPayments,
                c.StartDate,
                c.EndDate,
                c.RenterType,
                s.Adress AS ServerAdress,
                s.City AS ServerCity,
                e.Surname AS SellerSurname,
                e.Name AS SellerName,
                e.AccountNumber AS SellerAccountNumber
            FROM 
                contracts c
            LEFT JOIN 
                renterindividual ri ON c.Renter_ID = ri.ID_RenterIndividual AND c.RenterType = 'Individual'
            LEFT JOIN 
                renterlegal rl ON c.Renter_ID = rl.ID_RenterLegal AND c.RenterType = 'Legal'
            JOIN 
                servers s ON c.Server_ID = s.ID_Server
            JOIN 
                employees e ON c.Seller_ID = e.ID_Employee
            WHERE c.ID_Contracts = {contract_id};
        """
        cursor.execute(query)
        data = cursor.fetchone()
        cursor.close()  # Закрываем курсор после использования

        if data is None:
            error_queue.put("No contract data found.")
            return

        # Определение типа арендатора и соответствующего шаблона
        if data[8] == 'Individual':
            template_file = 'contract_template_individual.txt'
            renter_surname = data[1]
            renter_name = data[2]
            renter_legal_name = ""
        elif data[8] == 'Legal':
            template_file = 'contract_template_legal.txt'
            renter_surname = ""
            renter_name = ""
            renter_legal_name = data[3]

        # Чтение шаблона договора из файла
        with open(template_file, 'r', encoding='utf-8') as file:
            contract_template = file.read()

        # Подставляем данные в шаблон
        monthly_payment = data[5]
        start_date = data[6]
        end_date = data[7]
        seller_surname = data[12]
        seller_name = data[11]
        email = "nikita.buharinov@mail.ru"

        filled_contract = contract_template.format(
            renter_surname=renter_surname,
            renter_name=renter_name,
            renter_legal_name=renter_legal_name,
            monthly_payment=monthly_payment,
            start_date=start_date,
            end_date=end_date,
            seller_surname=seller_surname,
            seller_name=seller_name,
            email=email
        )

        # Кодировка текста перед записью в PDF
        encoded_text = filled_contract.encode('utf-8', errors='ignore').decode('utf-8')

        # Создание PDF-документа
        pdf = FPDF()
        pdf.add_page()
        pdf.add_font("DejaVuSans", "", "DejaVuSans.ttf", uni=True)
        pdf.set_font("DejaVuSans", size=10)

        for line in encoded_text.split('\n'):
            pdf.multi_cell(0, 5,
                           txt=line)

        pdf.output("rental_contract.pdf")
        os.startfile("rental_contract.pdf")
    except Exception as e:
        error_queue.put(e)


def update_back_button(text='Назад'):
    for widget in first_frame.winfo_children():
        if isinstance(widget, tk.Button) and widget['text'] in ['Меню выбора документов', 'Меню выбора таблиц',
                                                                'Назад']:
            widget['text'] = text


# Функция генерации прибыли по месяцам с гистограммой (главный поток)
def generate_profit_by_month_main(cnx, start_date, end_date, error_queue):
    try:
        cursor = cnx.cursor()
        query = f"""
            SELECT 
                YEAR(p.PaymentDate) AS Year,
                MONTH(p.PaymentDate) AS Month,
                SUM(p.PaymentAmount) AS TotalPayment
            FROM 
                payments p
            WHERE p.PaymentDate BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY 
                YEAR(p.PaymentDate), MONTH(p.PaymentDate)
            ORDER BY 
                Year, Month;
        """
        cursor.execute(query)
        data = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        cursor.close()

        if not data:
            error_queue.put("No payment data found.")
            return

        # Данные для графика
        months = [f"{row[0]}-{row[1]:02d}" for row in data]
        payments = [row[2] for row in data]

        # Создание графика в главном потоке
        plt.figure(figsize=(10, 5))
        plt.bar(months, payments)
        plt.xlabel('Месяц')
        plt.ylabel('Общая сумма платежей')
        plt.title('Прибыль по месяцам')
        plt.xticks(rotation=90)
        plt.tight_layout()

        # Сохранение графика как файл
        plt.savefig('profit_by_month_graph.png', dpi=300)

        # Создание PDF-документа
        pdf = FPDF()

        # Добавление первой страницы для графика
        pdf.add_page()

        # Включение графика в PDF-документ
        pdf.image('profit_by_month_graph.png', x=10, y=50, w=190)

        # Добавление второй страницы для таблицы
        pdf.add_page()

        # Заголовок таблицы
        pdf.add_font("DejaVuSans", "", "DejaVuSans.ttf", uni=True)
        pdf.set_font("DejaVuSans", size=12)

        # Заголовки таблицы
        pdf.cell(40, 10, txt="Год-Месяц", border=1, align='C')
        pdf.cell(60, 10, txt="Общая сумма платежей", border=1, align='C')

        # Переход на новую строку после заголовков
        pdf.ln(10)

        # Данные таблицы
        for i in range(len(data)):
            pdf.cell(40, 10, txt=f"{data[i][0]}-{data[i][1]:02d}", border=1, align='C')
            pdf.cell(60, 10, txt=str(data[i][2]), border=1, align='C')

            # Переход на новую строку после каждой строки данных
            pdf.ln(10)

        pdf.output("profit_by_month.pdf")
        os.startfile("profit_by_month.pdf")
    except Exception as e:
        error_queue.put(e)


def login_window():
    def login():
        global cnx, user_role
        user = user_entry.get().lower().strip()
        password = password_entry.get()

        if not all([user, password]):
            messagebox.showerror("Ошибка", "Все поля должны быть заполнены.")
            return

        user_role = user_roles.get(user, None)
        if user_role is None:
            messagebox.showerror("Ошибка", "Недопустимое имя пользователя.")
            return

        cnx = connect_to_db(user_role, password)

        if cnx is not None:
            for widget in login_frame.winfo_children():
                widget.destroy()
            login_frame.pack_forget()

            # Очистка места, где был логин фрейм
            for widget in root.winfo_children():
                if widget == login_frame:
                    widget.destroy()

            document_frame.pack(fill=tk.BOTH, expand=True)
            root.title("Интерфейс Базы Данных")  # Изменение названия программы
            update_back_button()  # Обновление текста кнопки "Назад"
        else:
            messagebox.showerror("Ошибка", "Неправильное имя пользователя или пароль.")

    def update_back_button():
        global user_role, cnx

        # Определение доступных таблиц в зависимости от роли пользователя
        if user_role in ['administrator', 'manager', 'root']:
            available_tables = ["servers", "models", "employees", "contracts", "payments",
                                "contractaggregatehistory", "contractpaymenthistory",
                                "contractrentedspacehistory", "contractstatushistory",
                                "payouts", "renterindividual", "renterlegal", "roles"]
        else:
            available_tables = ["contracts", "renterindividual", "renterlegal"]

        for widget in first_frame.winfo_children():
            if isinstance(widget, tk.Button) and widget['text'] in ["Назад", "Перейти к таблицам",
                                                                    "Перейти к выходным документам"]:
                if second_frame.winfo_children():
                    # Проверяем, есть ли кнопки с документами
                    doc_buttons = ["Статистика по серверам", "Договор аренды", "Прибыль по месяцам"]
                    doc_found = False
                    table_found = False

                    for child in second_frame.winfo_children():
                        if isinstance(child, tk.Frame):
                            for grandchild in child.winfo_children():
                                if isinstance(grandchild, tk.Button):
                                    if grandchild['text'] in doc_buttons:
                                        doc_found = True
                                    elif grandchild['text'] in available_tables:
                                        table_found = True

                    if doc_found:
                        widget['text'] = "Перейти к таблицам"
                    elif table_found:
                        widget['text'] = "Перейти к выходным документам"
                    else:
                        widget['text'] = "Назад"

    global login_frame
    style = Style(theme="superhero")
    root = style.master

    root.title("Авторизация")
    root.geometry("1200x1200")

    def on_close():
        root.destroy()

    login_frame = tk.Frame(root, bg="#F5F5DC")
    login_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    tk.Label(login_frame, text="Введите ваше имя и пароль", font=("Arial", 18), bg="#F5F5DC").pack(pady=10)
    frame_login = tk.Frame(login_frame, bg="#F5F5DC")
    frame_login.pack(pady=20)

    tk.Label(frame_login, text="Имя", bg="#F5F5DC", font=("Arial", 16)).grid(row=0, column=0, padx=10, pady=10)
    tk.Label(frame_login, text="Пароль", bg="#F5F5DC", font=("Arial", 16)).grid(row=1, column=0, padx=10, pady=10)

    global user_entry
    user_entry = tk.Entry(frame_login, font=("Arial", 16))
    user_entry.grid(row=0, column=1, padx=10, pady=10)

    global password_entry
    password_entry = tk.Entry(frame_login, show="*", font=("Arial", 16))
    password_entry.grid(row=1, column=1, padx=10, pady=10)

    tk.Button(frame_login, text="Подтвердить", command=login, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).grid(
        row=2, column=0, columnspan=2, padx=10, pady=20)


def show_documents():
    # Очистка содержимого first_frame и second_frame
    for widget in first_frame.winfo_children():
        widget.destroy()
    for widget in second_frame.winfo_children():
        widget.destroy()

    def go_back():
        show_db_management()

    tk.Button(first_frame, text="Назад", command=go_back, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(
        side=tk.TOP, pady=20)
    update_back_button('Меню выбора таблиц')

    # Кнопки для документов должны быть на втором фрейме
    buttons_frame = tk.Frame(second_frame)
    buttons_frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(buttons_frame, text="Документы", font=("Arial", 18), bg="#F5F5DC").pack(pady=10)

    tk.Button(buttons_frame, text="Статистика по серверам", command=get_server_stats_order, bg="#FFFFFF", fg="#000000",
              font=("Arial", 16)).pack(pady=20)
    tk.Button(buttons_frame, text="Договор аренды", command=get_contract_id, bg="#FFFFFF", fg="#000000",
              font=("Arial", 16)).pack(pady=20)
    tk.Button(buttons_frame, text="Прибыль по месяцам", command=get_dates, bg="#FFFFFF", fg="#000000",
              font=("Arial", 16)).pack(pady=20)


def get_server_stats_order():
    def get_order_by():
        order_by_window = Toplevel(root)
        order_by_window.title("Выбор порядка сортировки")

        tk.Label(order_by_window, text="Выберите порядок сортировки:", font=("Arial", 24)).pack(pady=40)
        tk.Button(order_by_window, text="По возрастанию", command=lambda: [order_by_window.destroy(),
                                                                           threading.Thread(
                                                                               target=generate_server_statistics,
                                                                               args=(cnx, 'ASC',
                                                                                     error_queue)).start()],
                  font=("Arial", 20)).pack(pady=20)
        tk.Button(order_by_window, text="По убыванию", command=lambda: [order_by_window.destroy(), threading.Thread(
            target=generate_server_statistics, args=(cnx, 'DESC', error_queue)).start()],
                  font=("Arial", 20)).pack(pady=20)

    get_order_by()
    update_back_button()  # Обновление текста кнопки "Назад"


def get_contract_id():
    contract_id = simpledialog.askinteger("Введите ID договора аренды", "ID договора аренды")
    if contract_id is not None:
        threading.Thread(target=generate_rental_contract, args=(cnx, contract_id, error_queue)).start()
    update_back_button()  # Обновление текста кнопки "Назад"


def get_dates():
    while True:
        start_date = simpledialog.askstring("Введите начальную дату", "Начальная дата (YYYY-MM-01)")
        end_date = simpledialog.askstring("Введите конечную дату", "Конечная дата (YYYY-MM-01)")

        # Проверка формата дат
        try:
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

            # Проверка того, что начальная дата не позднее конечной
            if start_date_obj > end_date_obj:
                messagebox.showerror("Ошибка", "Начальная дата должна быть раньше конечной.")
                continue

            generate_profit_by_month_main(cnx, start_date, end_date, error_queue)
            break
        except ValueError:
            messagebox.showerror("Ошибка", "Неправильный формат даты. Используйте YYYY-MM-01.")

    update_back_button()  # Обновление текста кнопки "Назад"


def db_management_window():
    global db_management_frame, error_queue

    update_back_button()  # Обновление текста кнопки "Назад"

    # Create a frame with a vertical scrollbar
    db_management_frame = tk.Frame(second_frame, bg="#F5F5DC", highlightbackground="black", highlightthickness=1)
    db_management_frame.pack(fill=tk.BOTH, expand=True)  # Используем fill=tk.BOTH и expand=True

    # Canvas for placing buttons
    canvas = tk.Canvas(db_management_frame, bg="#F5F5DC")
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)  # Используем fill=tk.BOTH и expand=True

    # Vertical scrollbar
    scrollbar = tk.Scrollbar(db_management_frame, command=canvas.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.configure(yscrollcommand=scrollbar.set)

    # Inner frame inside the canvas for buttons
    inner_frame = tk.Frame(canvas, bg="#F5F5DC")
    canvas.create_window((0, 0), window=inner_frame, anchor='nw')

    # Определение доступных таблиц в зависимости от роли пользователя
    if user_role in ['administrator', 'manager', 'root']:
        available_tables = ["servers", "models", "employees", "contracts", "payments",
                            "contractaggregatehistory", "contractpaymenthistory",
                            "contractrentedspacehistory", "contractstatushistory",
                            "payouts", "renterindividual", "renterlegal", "roles"]
    else:
        available_tables = ["contracts", "renterindividual", "renterlegal"]

    # Add buttons to the inner frame
    for i, table in enumerate(available_tables):
        btn = tk.Button(inner_frame, text=table, command=lambda t=table: show_table_options(t),
                        bg="#FFFFFF", fg="#000000", font=("Arial", 16))
        btn.grid(row=i // 3, column=i % 3, padx=10, pady=10)  # Use grid layout to arrange buttons in columns

    # Update the size of the canvas after adding buttons
    inner_frame.update_idletasks()
    canvas.configure(scrollregion=canvas.bbox("all"))


def show_table_options(table_name):
    update_back_button()  # Обновление текста кнопки "Назад"

    # Очистка содержимого first_frame и second_frame
    for widget in first_frame.winfo_children():
        widget.destroy()
    for widget in second_frame.winfo_children():
        widget.destroy()

    # Добавление кнопки "Назад"
    def go_back():
        show_db_management()

    tk.Button(first_frame, text="Назад", command=go_back, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(
        side=tk.TOP, pady=20)

    tk.Label(first_frame, text="Опции\nуправления\nтаблицей", font=("Arial", 18), bg="#F5F5DC").pack(pady=10)

    table_options_frame = tk.Frame(first_frame)
    table_options_frame.pack(fill=tk.BOTH, expand=True)

    tk.Button(table_options_frame, text="Просмотр", command=lambda: view_table(table_name),
              bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(side=tk.TOP, padx=20, pady=10)

    tk.Frame(table_options_frame, height=1, bg="#000000").pack(side=tk.TOP, fill=tk.X, padx=10, pady=2)

    tk.Button(table_options_frame, text="Корректировка", command=lambda: edit_table(table_name),
              bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(side=tk.TOP, padx=20, pady=10)

    tk.Frame(table_options_frame, height=1, bg="#000000").pack(side=tk.TOP, fill=tk.X, padx=10, pady=2)

    tk.Button(table_options_frame, text="Удаление", command=lambda: delete_table(table_name),
              bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(side=tk.TOP, padx=20, pady=10)

    tk.Frame(table_options_frame, height=1, bg="#000000").pack(side=tk.TOP, fill=tk.X, padx=10, pady=2)

    tk.Button(table_options_frame, text="Добавление", command=lambda: add_to_table(table_name),
              bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(side=tk.TOP, padx=20, pady=10)

    if table_name == 'contracts':
        def rollback_contracts():
            # Очистка содержимого first_frame и second_frame
            for widget in first_frame.winfo_children():
                widget.destroy()
            for widget in second_frame.winfo_children():
                widget.destroy()

            def go_back():
                show_table_options('contracts')

            tk.Button(first_frame, text="Назад", command=go_back, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(
                side=tk.TOP, pady=20)

            rollback_frame = tk.Frame(first_frame)
            rollback_frame.pack(fill=tk.BOTH, expand=True)

            tk.Label(rollback_frame, text="Введите дату для роллбэка (YYYY-MM-DD):", font=("Arial", 16)).pack(pady=10)
            date_entry = tk.Entry(rollback_frame)
            date_entry.pack(pady=10)

            def display_rollback_result():
                date = date_entry.get()
                if not date:
                    messagebox.showerror("Ошибка", "Дата должна быть указана.")
                    return

                query = f"""
                    SELECT 
                        c.ID_Contracts,
                        COALESCE(csh.Status, c.Status) AS Status,
                        COALESCE(cph.MonthlyPayment, c.MonthlyPayments) AS MonthlyPayment,
                        COALESCE(crsh.RentedSpace, c.RentedSpace) AS RentedSpace,
                        c.StartDate,
                        c.EndDate,
                        c.RenterType
                    FROM 
                        kursTemp.contracts c

                    LEFT JOIN (
                        SELECT 
                            ID_Contract_Contracts, 
                            MAX(StatusChangeDate) AS LastStatusChangeDate
                        FROM 
                            kursTemp.ContractStatusHistory
                        WHERE 
                            StatusChangeDate <= '{date}'
                        GROUP BY 
                            ID_Contract_Contracts
                    ) AS last_status ON c.ID_Contracts = last_status.ID_Contract_Contracts AND (c.StartDate <= '{date}' OR last_status.LastStatusChangeDate IS NULL)

                    LEFT JOIN (
                        SELECT 
                            ID_Contract_Contracts, 
                            Status, 
                            StatusChangeDate
                        FROM 
                            kursTemp.ContractStatusHistory
                        WHERE 
                            (ID_Contract_Contracts, StatusChangeDate) IN (
                                SELECT 
                                    ID_Contract_Contracts, 
                                    MAX(StatusChangeDate)
                                FROM 
                                    kursTemp.ContractStatusHistory
                                WHERE 
                                    StatusChangeDate <= '{date}'
                                GROUP BY 
                                    ID_Contract_Contracts
                            )
                    ) AS csh ON c.ID_Contracts = csh.ID_Contract_Contracts AND csh.StatusChangeDate = last_status.LastStatusChangeDate

                    LEFT JOIN (
                        SELECT 
                            ID_Contract_Contracts, 
                            MAX(PaymentChangeDate) AS LastPaymentChangeDate
                        FROM 
                            kursTemp.ContractPaymentHistory
                        WHERE 
                            PaymentChangeDate <= '{date}'
                        GROUP BY 
                            ID_Contract_Contracts
                    ) AS last_payment ON c.ID_Contracts = last_payment.ID_Contract_Contracts AND (c.StartDate <= '{date}' OR last_payment.LastPaymentChangeDate IS NULL)

                    LEFT JOIN (
                        SELECT 
                            ID_Contract_Contracts, 
                            MonthlyPayment, 
                            PaymentChangeDate
                        FROM 
                            kursTemp.ContractPaymentHistory
                        WHERE 
                            (ID_Contract_Contracts, PaymentChangeDate) IN (
                                SELECT 
                                    ID_Contract_Contracts, 
                                    MAX(PaymentChangeDate)
                                FROM 
                                    kursTemp.ContractPaymentHistory
                                WHERE 
                                    PaymentChangeDate <= '{date}'
                                GROUP BY 
                                    ID_Contract_Contracts
                            )
                    ) AS cph ON c.ID_Contracts = cph.ID_Contract_Contracts AND cph.PaymentChangeDate = last_payment.LastPaymentChangeDate

                    LEFT JOIN (
                        SELECT 
                            ID_Contract_Contracts, 
                            MAX(SpaceChangeDate) AS LastSpaceChangeDate
                        FROM 
                            kursTemp.ContractRentedSpaceHistory
                        WHERE 
                            SpaceChangeDate <= '{date}'
                        GROUP BY 
                            ID_Contract_Contracts
                    ) AS last_space ON c.ID_Contracts = last_space.ID_Contract_Contracts AND (c.StartDate <= '{date}' OR last_space.LastSpaceChangeDate IS NULL)

                    LEFT JOIN (
                        SELECT 
                            ID_Contract_Contracts, 
                            RentedSpace, 
                            SpaceChangeDate
                        FROM 
                            kursTemp.ContractRentedSpaceHistory
                        WHERE 
                            (ID_Contract_Contracts, SpaceChangeDate) IN (
                                SELECT 
                                    ID_Contract_Contracts, 
                                    MAX(SpaceChangeDate)
                                FROM 
                                    kursTemp.ContractRentedSpaceHistory
                                WHERE 
                                    SpaceChangeDate <= '{date}'
                                GROUP BY 
                                    ID_Contract_Contracts
                            )
                    ) AS crsh ON c.ID_Contracts = crsh.ID_Contract_Contracts AND crsh.SpaceChangeDate = last_space.LastSpaceChangeDate

                    WHERE c.StartDate <= '{date}';
                """

                cursor = cnx.cursor()
                cursor.execute(query)
                data = cursor.fetchall()
                if not data:
                    messagebox.showinfo("Результат", "Нет данных для указанной даты.")
                    return

                columns = [desc[0] for desc in cursor.description]
                cursor.close()

                for widget in second_frame.winfo_children():
                    widget.destroy()

                table_frame = tk.Frame(second_frame)
                table_frame.pack(fill=tk.BOTH, expand=True)

                canvas = tk.Canvas(table_frame)
                canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                scrollbar = tk.Scrollbar(table_frame, command=canvas.yview)
                scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                canvas.configure(yscrollcommand=scrollbar.set)

                inner_table_frame = tk.Frame(canvas)
                canvas.create_window((0, 0), window=inner_table_frame, anchor='nw')

                for i, col in enumerate(columns):
                    tk.Label(inner_table_frame, text=col).grid(row=0, column=i, padx=10, pady=10)

                for i, row in enumerate(data):
                    for j, cell in enumerate(row):
                        tk.Label(inner_table_frame, text=str(cell)).grid(row=i + 1, column=j, padx=10, pady=10)

                inner_table_frame.update_idletasks()
                canvas.configure(scrollregion=canvas.bbox("all"))

            tk.Button(rollback_frame, text="Показать результат", command=display_rollback_result,
                      bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(pady=20)

        tk.Button(table_options_frame, text="Роллбэк", command=rollback_contracts,
                  bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(side=tk.TOP, padx=20, pady=10)


def view_all_table(table_name):
    # Очистка содержимого второго фрейма
    for widget in second_frame.winfo_children():
        widget.destroy()

    # Frame для таблицы с вертикальным скроллбаром
    table_frame = tk.Frame(second_frame)
    table_frame.pack(fill=tk.BOTH, expand=True)

    # Canvas для таблицы
    canvas = tk.Canvas(table_frame)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    # Vertical scrollbar
    scrollbar = tk.Scrollbar(table_frame, command=canvas.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.configure(yscrollcommand=scrollbar.set)

    # Inner frame inside the canvas for table
    inner_table_frame = tk.Frame(canvas)
    canvas.create_window((0, 0), window=inner_table_frame, anchor='nw')

    # Получение названий столбцов
    cursor = cnx.cursor()
    query = f"SELECT * FROM {table_name} LIMIT 1"
    cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    cursor.fetchall()  # Прочитываем результаты запроса
    cursor.close()

    # Получение всех строк таблицы
    cursor = cnx.cursor()
    query = f"SELECT * FROM {table_name}"
    cursor.execute(query)
    data = cursor.fetchall()
    cursor.close()

    # Заголовки таблицы
    for i, col in enumerate(columns):
        tk.Label(inner_table_frame, text=col).grid(row=0, column=i, padx=10, pady=10)

    # Данные таблицы
    for i, row in enumerate(data):
        for j, cell in enumerate(row):
            tk.Label(inner_table_frame, text=str(cell)).grid(row=i + 1, column=j, padx=10, pady=10)

    # Update the size of the canvas after adding table data
    inner_table_frame.update_idletasks()
    canvas.configure(scrollregion=canvas.bbox("all"))


def view_table(table_name):
    # Очистка содержимого first_frame и second_frame
    for widget in first_frame.winfo_children():
        widget.destroy()
    for widget in second_frame.winfo_children():
        widget.destroy()

    # Добавление кнопки "Назад"
    def go_back():
        show_table_options(table_name)

    tk.Button(first_frame, text="Назад", command=go_back, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(
        side=tk.TOP, padx=20, pady=10)
    tk.Label(first_frame, text="Выберите\nнужные\nатрибуты", font=("Arial", 18), bg="#F5F5DC").pack(pady=10)

    view_table_frame = tk.Frame(first_frame)
    view_table_frame.pack(fill=tk.BOTH, expand=True)

    view_all_table(table_name)

    # Checkbox для каждого столбца
    checkboxes = {}
    conditions_entries = {}
    cursor = cnx.cursor()
    query = f"SELECT * FROM {table_name} LIMIT 1"
    cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    cursor.fetchall()
    cursor.close()

    for col in columns:
        frame = tk.Frame(view_table_frame)
        frame.pack(pady=10)

        var = tk.IntVar()
        checkboxes[col] = var

        tk.Checkbutton(frame, text=col, variable=var).pack(side=tk.LEFT, padx=5)

        condition_label = tk.Label(frame, text="Условие:")
        condition_label.pack(side=tk.LEFT, padx=5)

        condition_entry = tk.Entry(frame)
        condition_entry.pack(side=tk.LEFT, padx=5)

        conditions_entries[col] = condition_entry

    def select_all():
        for var in checkboxes.values():
            var.set(1)

    tk.Button(view_table_frame, text="Отметить все", command=select_all, bg="#FFFFFF", fg="#000000",
              font=("Arial", 16)).pack(side=tk.TOP, padx=20, pady=10)

    # Поле для количества строк
    tk.Label(view_table_frame, text="Количество строк").pack(pady=10)
    row_count_entry = tk.Entry(view_table_frame)
    row_count_entry.pack(pady=10)

    def display_table():
        selected_columns = [col for col, var in checkboxes.items() if var.get()]
        conditions = {col: entry.get() for col, entry in conditions_entries.items()}

        row_count = row_count_entry.get()

        if not selected_columns:
            messagebox.showerror("Ошибка", "Не выбраны столбцы для отображения.")
            return

        query = f"SELECT {', '.join(selected_columns)} FROM {table_name}"

        # Добавляем условия в запрос
        where_conditions = []
        for col, condition in conditions.items():
            if condition:
                where_conditions.append(f"{col} {condition}")

        if where_conditions:
            query += " WHERE " + " AND ".join(where_conditions)

        if row_count:
            query += f" LIMIT {row_count}"

        cursor = cnx.cursor()
        cursor.execute(query)
        data = cursor.fetchall()
        cursor.close()

        for widget in second_frame.winfo_children():
            widget.destroy()

        table_frame = tk.Frame(second_frame)
        table_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(table_frame)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(table_frame, command=canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.configure(yscrollcommand=scrollbar.set)

        inner_table_frame = tk.Frame(canvas)
        canvas.create_window((0, 0), window=inner_table_frame, anchor='nw')

        for i, col in enumerate(selected_columns):
            tk.Label(inner_table_frame, text=col).grid(row=0, column=i, padx=10, pady=10)

        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                tk.Label(inner_table_frame, text=str(cell)).grid(row=i + 1, column=j, padx=10, pady=10)

        inner_table_frame.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

    tk.Button(view_table_frame, text="Показать таблицу", command=display_table, bg="#FFFFFF", fg="#000000",
              font=("Arial", 16)).pack(pady=20)


def edit_table(table_name):
    # Очистка содержимого first_frame и second_frame
    for widget in first_frame.winfo_children():
        widget.destroy()
    for widget in second_frame.winfo_children():
        widget.destroy()

    def go_back():
        show_table_options(table_name)

    tk.Button(first_frame, text="Назад", command=go_back, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(
        side=tk.TOP, pady=20)
    tk.Label(first_frame, text="Выберите\nнужные\nатрибуты", font=("Arial", 18), bg="#F5F5DC").pack(pady=10)

    edit_table_frame = tk.Frame(first_frame)
    edit_table_frame.pack(fill=tk.BOTH, expand=True)

    view_all_table(table_name)

    cursor = cnx.cursor()
    query = f"SELECT * FROM {table_name} LIMIT 1"
    cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    cursor.fetchall()
    cursor.close()

    primary_key_query = f"SHOW KEYS FROM {table_name} WHERE Key_name = 'PRIMARY'"
    cursor = cnx.cursor()
    cursor.execute(primary_key_query)
    primary_key_result = cursor.fetchone()
    cursor.close()

    if primary_key_result:
        primary_key_column = primary_key_result[4]
    else:
        messagebox.showerror("Ошибка", "Не удалось определить первичный ключ.")
        return

    # Frame для ввода IDs
    ids_frame = tk.Frame(edit_table_frame)
    ids_frame.pack(pady=10)

    tk.Label(ids_frame, text=f"Введите {primary_key_column}(ы) через запятую:").pack(side=tk.LEFT, padx=5)

    ids_entry = tk.Entry(ids_frame)
    ids_entry.pack(side=tk.LEFT, padx=5)

    checkboxes = {}
    new_data_entries = {}

    non_pk_columns = [col for col in columns if col != primary_key_column]

    for i, col in enumerate(non_pk_columns):
        frame = tk.Frame(edit_table_frame)
        frame.pack(pady=5)

        var = tk.IntVar()
        checkboxes[col] = var

        tk.Checkbutton(frame, text=col, variable=var).pack(side=tk.LEFT, padx=5)

        entry = tk.Entry(frame)
        entry.pack(side=tk.LEFT, padx=5)

        new_data_entries[col] = entry

    def select_all():
        for var in checkboxes.values():
            var.set(1)

    tk.Button(edit_table_frame, text="Отметить все", command=select_all, bg="#FFFFFF", fg="#000000",
              font=("Arial", 16)).pack(pady=20)

    def update_tables():
        ids_list = ids_entry.get().split(',')
        ids_list = [id.strip() for id in ids_list]

        if not ids_list:
            messagebox.showerror("Ошибка", "IDs должны быть указаны.")
            return

        selected_columns = [col for col in non_pk_columns if checkboxes[col].get()]
        new_data = {col: entry.get() for col, entry in new_data_entries.items() if checkboxes[col].get()}

        if not new_data:
            messagebox.showerror("Ошибка", "Не выбраны столбцы для обновления.")
            return

        # Construct the UPDATE query
        query = f"UPDATE {table_name} SET "
        update_query = []
        for col in selected_columns:
            update_query.append(f"{col} = %s")

        query += ", ".join(update_query)
        query += f" WHERE {primary_key_column} = %s"

        # Prepare the values list correctly
        values_list = []
        for id in ids_list:
            values = [new_data[col] for col in selected_columns] + [id]
            values_list.append(values)

        cursor = cnx.cursor()
        cursor.executemany(query, values_list)
        cnx.commit()
        cursor.close()
        messagebox.showinfo("Успех", "Строки обновлены успешно.")
        view_all_table(table_name)

    tk.Button(edit_table_frame, text="Обновить строки", command=update_tables, bg="#FFFFFF", fg="#000000",
              font=("Arial", 16)).pack(pady=20)


def delete_table(table_name):
    # Очистка содержимого first_frame и second_frame
    for widget in first_frame.winfo_children():
        widget.destroy()
    for widget in second_frame.winfo_children():
        widget.destroy()

    def go_back():
        show_table_options(table_name)

    tk.Button(first_frame, text="Назад", command=go_back, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(
        side=tk.TOP, pady=20)
    tk.Label(first_frame, text="Веедите\nномер\nстроки", font=("Arial", 18), bg="#F5F5DC").pack(pady=10)

    delete_table_frame = tk.Frame(first_frame)
    delete_table_frame.pack(fill=tk.BOTH, expand=True)

    view_all_table(table_name)

    cursor = cnx.cursor()
    query = f"SELECT * FROM {table_name} LIMIT 1"
    cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    cursor.fetchall()
    cursor.close()

    primary_key_query = f"SHOW KEYS FROM {table_name} WHERE Key_name = 'PRIMARY'"
    cursor = cnx.cursor()
    cursor.execute(primary_key_query)
    primary_key_result = cursor.fetchone()
    cursor.close()

    if primary_key_result:
        primary_key_column = primary_key_result[4]
    else:
        messagebox.showerror("Ошибка", "Не удалось определить первичный ключ.")
        return

    # Frame для ввода IDs
    ids_frame = tk.Frame(delete_table_frame)
    ids_frame.pack(pady=10)

    tk.Label(ids_frame, text=f"Введите {primary_key_column}(ы) через запятую:").pack(side=tk.LEFT, padx=5)

    ids_entry = tk.Entry(ids_frame)
    ids_entry.pack(side=tk.LEFT, padx=5)

    def delete_rows():
        ids_list = ids_entry.get().split(',')
        ids_list = [id.strip() for id in ids_list]

        if not ids_list:
            messagebox.showerror("Ошибка", "IDs должны быть указаны.")
            return

        query = f"DELETE FROM {table_name} WHERE {primary_key_column} IN ({', '.join(['%s'] * len(ids_list))})"
        cursor = cnx.cursor()
        cursor.execute(query, ids_list)
        cnx.commit()
        cursor.close()
        messagebox.showinfo("Успех", "Строки удалены успешно.")
        view_all_table(table_name)

    tk.Button(delete_table_frame, text="Удалить строки", command=delete_rows, bg="#FFFFFF", fg="#000000",
              font=("Arial", 16)).pack(pady=20)


def add_to_table(table_name):
    # Очистка содержимого first_frame и second_frame
    for widget in first_frame.winfo_children():
        widget.destroy()
    for widget in second_frame.winfo_children():
        widget.destroy()

    def go_back():
        show_table_options(table_name)

    tk.Button(first_frame, text="Назад", command=go_back, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(
        side=tk.TOP, pady=20)
    tk.Label(first_frame, text="Веедите\nзначения\nстроки", font=("Arial", 18), bg="#F5F5DC").pack(pady=10)

    add_to_table_frame = tk.Frame(first_frame)
    add_to_table_frame.pack(fill=tk.BOTH, expand=True)

    view_all_table(table_name)

    cursor = cnx.cursor()
    query = f"SELECT * FROM {table_name} LIMIT 1"
    cursor.execute(query)
    columns = [desc[0] for desc in cursor.description]
    cursor.fetchall()
    cursor.close()

    # Исключаем первичный ключ из списка столбцов для ввода
    primary_key_query = f"SHOW KEYS FROM {table_name} WHERE Key_name = 'PRIMARY'"
    cursor = cnx.cursor()
    cursor.execute(primary_key_query)
    primary_key_result = cursor.fetchone()
    cursor.close()

    if primary_key_result:
        primary_key_column = primary_key_result[4]
        columns_without_pk = [col for col in columns if col != primary_key_column]
    else:
        columns_without_pk = columns

    new_data_entries = {}
    for i, col in enumerate(columns_without_pk):
        frame = tk.Frame(add_to_table_frame)
        frame.pack(pady=5)
        tk.Label(frame, text=f"Значение для {col}").pack(side=tk.LEFT, padx=10)
        entry = tk.Entry(frame)
        entry.pack(side=tk.LEFT, padx=10)
        new_data_entries[col] = entry

    def insert_row():
        query = f"INSERT INTO {table_name} ({', '.join(columns_without_pk)}) VALUES ({', '.join(['%s'] * len(columns_without_pk))})"

        # Если есть первичный ключ с auto_increment, то он сам будет генерироваться базой данных.
        values = [entry.get() for entry in new_data_entries.values()]

        cursor = cnx.cursor()
        cursor.execute(query, values)
        cnx.commit()
        cursor.close()

        # Если нет auto_increment, можно найти максимальный ID и добавить 1.
        # Однако, это не рекомендуется из-за потенциальных проблем с конкуренцией доступа.
        # query_for_max_id = f"SELECT MAX({primary_key_column}) FROM {table_name}"
        # cursor.execute(query_for_max_id)
        # max_id = cursor.fetchone()[0] + 1
        # values.insert(0, max_id)  # Вставляем ID в начало списка значений.

        view_all_table(table_name)

    tk.Button(add_to_table_frame, text="Добавить строку", command=insert_row, bg="#FFFFFF", fg="#000000",
              font=("Arial", 16)).pack(pady=20)


# Добавление раздела "Ведение БД" в главное меню
def show_db_management():
    # Очистка содержимого first_frame и second_frame
    for widget in first_frame.winfo_children():
        widget.destroy()
    for widget in second_frame.winfo_children():
        widget.destroy()

    def go_back():
        show_documents()

    tk.Button(first_frame, text="Назад", command=go_back, bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(
        side=tk.TOP, pady=20)
    update_back_button('Меню выбора документов')
    tk.Label(second_frame, text="Таблицы", font=("Arial", 18), bg="#F5F5DC").pack(pady=10)

    db_management_frame = tk.Frame(second_frame)
    db_management_frame.pack(fill=tk.BOTH, expand=True)

    canvas = tk.Canvas(db_management_frame)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    scrollbar = tk.Scrollbar(db_management_frame, command=canvas.yview)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.configure(yscrollcommand=scrollbar.set)

    inner_frame = tk.Frame(canvas)
    canvas.create_window((0, 0), window=inner_frame, anchor='nw')

    # Определение доступных таблиц в зависимости от роли пользователя
    if user_role in ['administrator', 'manager', 'root']:
        available_tables = ["servers", "models", "employees", "contracts", "payments",
                            "contractaggregatehistory", "contractpaymenthistory",
                            "contractrentedspacehistory", "contractstatushistory",
                            "payouts", "renterindividual", "renterlegal", "roles"]
    else:
        available_tables = ["contracts", "renterindividual", "renterlegal"]

    # Add buttons to the inner frame
    for i, table in enumerate(available_tables):
        btn = tk.Button(inner_frame, text=table, command=lambda t=table: show_table_options(t),
                        bg="#FFFFFF", fg="#000000", font=("Arial", 16))
        btn.grid(row=i // 3, column=i % 3, padx=10, pady=10)  # Use grid layout to arrange buttons in columns

    # Update the size of the canvas after adding buttons
    inner_frame.update_idletasks()
    canvas.configure(scrollregion=canvas.bbox("all"))


# Добавление кнопок в главное меню
global root
style = Style(theme="superhero")
root = style.master

root.title("Авторизация")
root.geometry("1200x1200")

global login_frame
login_frame = tk.Frame(root, bg="#F5F5DC")
login_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

global document_frame
document_frame = tk.Frame(root, bg="#F5F5DC")
document_frame.pack_forget()

global first_frame
first_frame = tk.Frame(document_frame, bg="#F5F5DC", highlightbackground="black", highlightthickness=1)
first_frame.pack(side=tk.LEFT, fill=tk.Y)

global second_frame
second_frame = tk.Frame(document_frame, bg="#F5F5DC", highlightbackground="black", highlightthickness=1)
second_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

tk.Button(first_frame, text="Выходные документы", command=show_documents,
          bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(pady=20)

tk.Button(first_frame, text="Ведение БД", command=show_db_management,
          bg="#FFFFFF", fg="#000000", font=("Arial", 16)).pack(pady=20)


# Кнопка "Об авторе"
def show_author_info():
    # Сохраняем текущий стиль
    current_style = Style().theme

    # Устанавливаем стиль в "null", чтобы использовать стандартные стили tkinter
    Style().theme = "null"

    # Создаем окно
    author_window = tk.Toplevel(root)
    author_window.title("Об авторе")
    author_window.geometry("600x600")

    # Убедитесь, что окно не наследует стиль от основного приложения
    # Используем стандартный tkinter вместо ttkbootstrap
    author_window.configure(bg="#FFFFFF")  # Белый фон для окна

    # Разделяем окно на 6 частей с разными цветами фона
    frame_height = 100
    total_height = 600

    # Красный фон
    frame1 = tk.Frame(author_window, bg="#FF0000", height=frame_height)
    frame1.pack(fill=tk.X)

    # Оранжевый фон
    frame2 = tk.Frame(author_window, bg="#FFA500", height=frame_height)
    frame2.pack(fill=tk.X)

    # Желтый фон
    frame3 = tk.Frame(author_window, bg="#FFFF00", height=frame_height)
    frame3.pack(fill=tk.X)

    # Зеленый фон
    frame4 = tk.Frame(author_window, bg="#008000", height=frame_height)
    frame4.pack(fill=tk.X)

    # Синий фон
    frame5 = tk.Frame(author_window, bg="#0000FF", height=frame_height)
    frame5.pack(fill=tk.X)

    # Фиолетовый фон
    frame6 = tk.Frame(author_window, bg="#800080", height=frame_height)
    frame6.pack(fill=tk.X)

    # Отображение информации об авторе на каждом фрейме
    tk.Label(frame1, text="Разработчик:", fg="#FFFFFF", bg="#FF0000", font=("Arial", 24)).place(relx=0.5, rely=0.5,
                                                                                                anchor=tk.CENTER)
    tk.Label(frame2, text="Бухаринов", fg="#000000", bg="#FFA500", font=("Arial", 24)).place(relx=0.5, rely=0.5,
                                                                                             anchor=tk.CENTER)
    tk.Label(frame3, text="Никита", fg="#000000", bg="#FFFF00", font=("Arial", 24)).place(relx=0.5, rely=0.5,
                                                                                          anchor=tk.CENTER)
    tk.Label(frame4, text="ИС3-2", fg="#FFFFFF", bg="#008000", font=("Arial", 20)).place(relx=0.5, rely=0.4,
                                                                                         anchor=tk.CENTER)
    tk.Label(frame5, text="Программа для управления", fg="#FFFFFF", bg="#0000FF", font=("Arial", 20)).place(relx=0.5,
                                                                                                            rely=0.4,
                                                                                                            anchor=tk.CENTER)
    tk.Label(frame6, text="Базой данных", fg="#FFFFFF", bg="#800080", font=("Arial", 24)).place(relx=0.5, rely=0.5,
                                                                                                anchor=tk.CENTER)

    # Закрываем окно и восстанавливаем стиль
    def close_window():
        author_window.destroy()
        Style().theme = current_style

    author_window.protocol("WM_DELETE_WINDOW", close_window)
    root.wait_window(author_window)


tk.Button(first_frame, text="Об авторе", command=show_author_info,
          bg="#FFC0CB", fg="#000000", font=("Arial", 16)).pack(pady=20)  # Розовая кнопка

error_queue = Queue()


def check_errors():
    while True:
        error = error_queue.get()
        if error:
            messagebox.showerror("Ошибка", str(error))


threading.Thread(target=check_errors).start()

login_window()

if __name__ == "__main__":
    root.mainloop()